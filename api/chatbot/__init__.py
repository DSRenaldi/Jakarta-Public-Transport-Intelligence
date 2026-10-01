# -*- coding: utf-8 -*-
"""Paket chatbot JPTI (Fase 5, arsitektur "B").

Komponen:
  intents.py  — classifier intent ML klasik (TF-IDF + RandomForest)
  llm.py      — klien LLM (Groq, OpenAI-compatible) + ekstraksi slot JSON
  tools.py    — tool: rute (netload), ridership, RAG
  session.py  — session memory in-memory (Redis menyusul)
  chat.py     — orkestrator: cache → intent → slot → tool → jawaban
"""
__version__ = "0.1.0"
