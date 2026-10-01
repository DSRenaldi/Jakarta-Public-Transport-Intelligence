# -*- coding: utf-8 -*-
"""Classifier intent chatbot JPTI — arsitektur "B" (ML klasik, tanpa LLM).

Model: TF-IDF (word unigram+bigram) + RandomForestClassifier (ensemble
decision tree), dilatih dari pertanyaan berlabel `intent_dataset.jsonl`
dan dievaluasi pada holdout stratified 20% (metrik §24.2: akurasi intent).

Aturan batas antar intent (diterapkan pada dataset; acuan saat evaluasi):
- Tanya perjalanan antar dua titik → `route_planning`, meskipun ikut
  menanyakan durasi, jumlah transit, atau tarif (rute + OD yang sama).
- "Jam berapa X paling ramai/padat/longgar?" → `crowding` (pola waktu),
  meskipun menyebut asal-tujuan.
- "Berapa tarif X?" tanpa pasangan asal-tujuan → `fare_query`.
- Peringkat stasiun/halte ("stasiun mana paling ramai") → `station_ranking`.
- Pertanyaan dokumen/kebijakan/metodologi/fasilitas → `policy_document`.
- Sapaan, terima kasih, off-topic → `other`.

Artefak (di-gitignore, bisa dibangun ulang):
  data/processed/intent_model.joblib
  data/processed/intent_eval.json

Jalankan langsung untuk latih ulang + lihat metrik:
  .venv\\Scripts\\python -m api.chatbot.intents
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines"))

DATASET = Path(__file__).resolve().parent / "intent_dataset.jsonl"
ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "data" / "processed" / "intent_model.joblib"
EVAL_PATH = ROOT / "data" / "processed" / "intent_eval.json"

INTENTS = [
    "route_planning",
    "ridership_statistics",
    "mode_comparison",
    "station_ranking",
    "fare_query",
    "schedule_query",
    "crowding",
    "policy_document",
    "other",
]

_PIPELINE = None
_METRICS = None


# ---------- aturan disambiguasi deterministik ----------
# Diterapkan SETELAH model: pola "kapan/berapa lama SEPI/PADAT/LONGGAR"
# menang atas route/schedule karena frasa "dari X ke Y" adalah sinyal rute
# yang sangat kuat, padahal inti pertanyaannya adalah pola waktu kepadatan.
# Pengecualian: station_ranking ("stasiun mana yang paling ramai" = ranking,
# bukan pola waktu) dan policy_document.
_CROWD_RE = re.compile(r"""
    \bpaling\s+(?:ramai|padat|sepi|longgar|sesak|penuh)\b
  | \bpadatkah\b
  | \b(?:rame|ramai|padat|sepi)\s+(?:ga|nggak|nggk)\b
  | \bkapan\b.{0,50}\b(?:ramai|padat|sepi|longgar|sesak|penuh)\b
  | \b(?:apakah|gimana|bagaimana)\b.{0,50}\b(?:ramai|padat|sepi|longgar|sesak|penuh)\b
  | \b(?:pagi|siang|sore|malam|hari kerja|akir pekan|akhir pekan|weekend|libur)\b.{0,25}\b(?:ramai|padat|sepi|longgar|sesak|penuh)\b
  | \b(?:ramai|padat|sepi|longgar|sesak|penuh)\b.{0,25}\b(?:pagi|siang|sore|malam|hari kerja|akhir pekan|weekend|libur|jam sibuk)\b
  | \bwaktu\s+(?:longgar|padat|sepi|ramai)\b
  | \bbiasanya\b.{0,30}\b(?:ramai|padat|sepi|longgar|sesak|penuh|rame)\b
""", re.IGNORECASE | re.VERBOSE)
_CROWD_EXCLUDE = {"station_ranking", "policy_document"}


def _rule_override(text: str, intent: str) -> str | None:
    """Aturan deterministik sempit yang menutup celah residual model."""
    t = text.lower()
    # "jam berapa penumpang [X] paling banyak" = pola waktu kepadatan,
    # bukan statistik (pola ini sengaja tidak masuk _CROWD_RE agar tidak
    # menimpa "moda apa yang penumpangnya paling banyak" = perbandingan).
    if intent != "crowding" and re.search(
            r"\bjam berapa\b.{0,40}\bpenumpang\b.{0,25}\bpaling\s+banyak\b",
            t):
        return "crowding"
    # peringkat stasiun berbasis tap-in/out
    if re.search(r"\bstasiun dengan tap\s?(?:in|out) terbanyak\b", t):
        return "station_ranking"
    if re.search(r"\bhalte tersibuk\b", t):
        return "station_ranking"
    if intent not in _CROWD_EXCLUDE and _CROWD_RE.search(text):
        return "crowding"
    return None


def load_dataset() -> list[tuple[str, str]]:
    items = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        assert row["intent"] in INTENTS, f"intent tidak dikenal: {row['intent']}"
        items.append((row["q"], row["intent"]))
    return items


def _build_pipeline():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion, Pipeline

    # Word unigram+bigram menangkap frasa intent ("jam operasional",
    # "berapa penumpang"); char_wb 3-5 memberi kekebalan terhadap
    # variasi ejaan kasual/typo ("brp", "gimana", "padatkah").
    return Pipeline([
        ("feat", FeatureUnion([
            ("word", TfidfVectorizer(
                lowercase=True, analyzer="word", ngram_range=(1, 2),
                sublinear_tf=True, min_df=1)),
            ("char", TfidfVectorizer(
                lowercase=True, analyzer="char_wb", ngram_range=(3, 5),
                sublinear_tf=True, min_df=1)),
        ])),
        ("clf", RandomForestClassifier(
            n_estimators=300,
            max_features="sqrt",
            random_state=42,
            n_jobs=2,
        )),
    ])


def evaluate() -> dict:
    """Latih ulang + evaluasi holdout stratified. Simpan artefak."""
    from sklearn.metrics import accuracy_score, classification_report, f1_score
    from sklearn.model_selection import train_test_split

    items = load_dataset()
    X = [t for t, _ in items]
    y = [i for _, i in items]
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y)

    pipe = _build_pipeline()
    pipe.fit(X_tr, y_tr)
    pred = pipe.predict(X_te)
    metrics = {
        "n_train": len(X_tr),
        "n_test": len(X_te),
        "accuracy": round(accuracy_score(y_te, pred), 4),
        "f1_macro": round(f1_score(y_te, pred, average="macro"), 4),
        "report": classification_report(y_te, pred, zero_division=0),
        "intents": {c: y.count(c) for c in INTENTS},
    }
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump(pipe, MODEL_PATH)
    EVAL_PATH.write_text(json.dumps(metrics, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return metrics


def _get():
    global _PIPELINE, _METRICS
    if _PIPELINE is None:
        if MODEL_PATH.exists() and EVAL_PATH.exists():
            import joblib
            _PIPELINE = joblib.load(MODEL_PATH)
            _METRICS = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
        else:
            _METRICS = evaluate()
            _PIPELINE = _build_pipeline()
            import joblib
            # evaluate() sudah menyimpan; muat ulang utk konsisten
            _PIPELINE = joblib.load(MODEL_PATH)
    return _PIPELINE, _METRICS


def classify(text: str) -> tuple[str, float]:
    """Kembalikan (intent, probabilitas) untuk satu pertanyaan.

    Probabilitas = dari model; aturan disambiguasi deterministik
    (_rule_override) dapat mengganti label akhir bila pola terdeteksi
    jelas. Aturan didokumentasikan untuk evaluasi (§24).
    """
    pipe, _ = _get()
    proba = pipe.predict_proba([text])[0]
    idx = int(proba.argmax())
    intent = str(pipe.classes_[idx])
    p = float(proba[idx])
    override = _rule_override(text, intent)
    if override:
        return override, p
    return intent, p


def status() -> dict:
    _, m = _get()
    return {
        "model": "tfidf word(1-2)+char_wb(3-5) + random_forest(300)",
        "accuracy_holdout": m["accuracy"],
        "f1_macro": m["f1_macro"],
        "n_train": m["n_train"],
        "n_test": m["n_test"],
        "intents": m["intents"],
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    m = evaluate()
    print(f"[intent] n_train={m['n_train']} n_test={m['n_test']} "
          f"accuracy={m['accuracy']} f1_macro={m['f1_macro']}")
    print(m["report"])
    for demo in [
        "berapa lama dari lebak bulus ke bogor",
        "berapa penumpang mrt 2025",
        "jam operasional lrt jakarta",
        "jam berapa stasiun dukuh atas paling padat",
        "halo, apa kabar",
    ]:
        intent, p = classify(demo)
        print(f"  {demo!r} -> {intent} ({p:.2f})")
