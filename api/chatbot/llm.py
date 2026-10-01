# -*- coding: utf-8 -*-
"""Klien LLM untuk chatbot JPTI — Groq (endpoint OpenAI-compatible).

LLM HANYA menyusun bahasa dari konteks yang sudah dikumpulkan tool
(routing/DB/RAG); bukan sumber angka (prinsip §7, §9 context.md).
Ekstraksi slot dilakukan dengan permintaan JSON ketat.

Konfigurasi (di .env, jangan disalin ke memori/dokumen):
  GROQ_API_KEY=***
  GROQ_MODEL=llama-3.3-70b-versatile   # opsional
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines"))
from db import load_env  # noqa: E402

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
TIMEOUT_SEC = 90.0

# Prioritas model chat bila model default tak ada di akun (akses model Groq
# berbeda per akun/wilayah; daftar diverifikasi via GET /models).
_MODEL_PRIORITY = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
]
_MODEL_SKIP = ("safeguard", "prompt-guard", "whisper")
_resolved_model = None


def _env() -> dict:
    return load_env()


def configured() -> bool:
    return bool(_env().get("GROQ_API_KEY", "").strip())


def _pick_model(ids: list[str]) -> str | None:
    for p in _MODEL_PRIORITY:
        if p in ids:
            return p
    for i in ids:
        if not any(s in i.lower() for s in _MODEL_SKIP):
            return i
    return None


def model_name() -> str:
    """Model yang dipakai: pin `GROQ_MODEL` (bila diset) > resolusi otomatis
    dari daftar model akun (dicache per proses) > default."""
    global _resolved_model
    env = _env()
    pin = env.get("GROQ_MODEL", "").strip()
    if pin:
        return pin
    if _resolved_model:
        return _resolved_model
    key = env.get("GROQ_API_KEY", "").strip()
    if key:
        try:
            resp = httpx.get(GROQ_MODELS_URL,
                             headers={"Authorization": f"Bearer {key}"},
                             timeout=30.0)
            resp.raise_for_status()
            ids = [m.get("id", "") for m in resp.json().get("data", [])]
            pick = _pick_model(ids)
            if pick:
                _resolved_model = pick
                if pick != DEFAULT_MODEL:
                    print(f"[llm] model default tak tersedia di akun — "
                          f"memakai {pick}", flush=True)
                return pick
        except httpx.HTTPError as e:
            print(f"[llm] gagal mengambil daftar model Groq: {e}", flush=True)
    return DEFAULT_MODEL


class LLMError(RuntimeError):
    pass


def chat(messages: list[dict], temperature: float = 0.15,
         max_tokens: int = 900) -> str:
    """Satu panggilan chat completion; 1x retry utk error jaringan /
    rate-limit / error server (kesalahan DNS sesaat, dsb.)."""
    env = _env()
    key = env.get("GROQ_API_KEY", "").strip()
    if not key:
        raise LLMError("GROQ_API_KEY belum diset di .env")
    resp = None
    for attempt in (1, 2):
        try:
            resp = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": model_name(), "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=TIMEOUT_SEC,
            )
        except httpx.HTTPError as e:
            if attempt == 1:
                time.sleep(1.5)
                continue
            raise LLMError(f"jaringan ke Groq gagal: {e}") from e
        if resp.status_code in (408, 425, 429, 500, 502, 503, 504) \
                and attempt == 1:
            wait = 2.0
            if resp.status_code == 429:
                # free tier: jendela TPM rolling — hormati "try again in X s"
                # (sleep tetap dibatasi 10 dtk; jika tetap gagal, jawaban
                # jatuh ke template fallback)
                m = re.search(r"try again in ([\d.]+)s", resp.text, re.I)
                if m:
                    wait = min(max(float(m.group(1)) + 0.5, 2.0), 10.0)
            time.sleep(wait)
            continue
        break
    if resp is None:
        raise LLMError("tidak ada respons dari Groq")
    if resp.status_code != 200:
        raise LLMError(f"Groq HTTP {resp.status_code}: "
                       f"{resp.text[:300]}")
    data = resp.json()
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError) as e:
        raise LLMError(f"respons Groq tidak terduga: {str(data)[:300]}") from e
    content = ((choice.get("message") or {}).get("content") or "").strip()
    if choice.get("finish_reason") == "length" and len(content) < 400:
        # Jawaban kita dibatasi ~170 kata; truncation di bawah 400 char
        # = respons terpotong (sering saat limit TPM akun tersentuh di
        # tengah generasi). Jangan sajikan setengah kalimat: retry 1x,
        # bila masih terpotong → LLMError → template fallback (lengkap).
        if attempt == 1:
            print("[llm] respons terpotong (finish_reason=length) — retry",
                  flush=True)
            time.sleep(1.0)
            try:
                resp2 = httpx.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": model_name(), "messages": messages,
                          "temperature": temperature,
                          "max_tokens": max_tokens},
                    timeout=TIMEOUT_SEC,
                )
            except httpx.HTTPError:
                raise LLMError("retry LLM gagal (jaringan); "
                               "pakai template")
            if resp2.status_code == 200:
                d2 = resp2.json()
                c2 = (d2.get("choices", [{}])[0]
                      .get("message", {}).get("content") or "").strip()
                if (len(c2) >= 400
                        or d2["choices"][0].get("finish_reason") != "length"):
                    return c2
        raise LLMError("LLM terpotong (finish_reason=length) dua kali; "
                       "pakai template")
    if not content:
        raise LLMError("LLM mengembalikan konten kosong")
    return content


def extract_json(system: str, user: str, max_tokens: int = 300) -> dict:
    """Panggilan LLM yang diwajibkan menjawab JSON object; parse robust."""
    raw = chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.0, max_tokens=max_tokens)
    # buang code fence bila ada
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"LLM tidak menjawab JSON: {raw[:200]}")
        raw = raw[start:end + 1]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON LLM tidak valid: {e}: {raw[:200]}") from e
    return obj if isinstance(obj, dict) else {}
