"""Central configuration. Reads .env once and exposes plain constants."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

CHROMA_DIR = ROOT / os.getenv("CHROMA_DIR", ".chroma")
DATA_DIR = ROOT / "data"
UPLOAD_DIR = ROOT / "uploads"

UPLOAD_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Planner/narrator generation settings
PLANNER_TEMPERATURE = 0.0
NARRATOR_TEMPERATURE = 0.2
MAX_RETRIEVED_CHUNKS = 4

# Row count above which we sample for expensive profiling operations
PROFILE_SAMPLE_ROWS = 200_000


def has_api_key() -> bool:
    return bool(GROQ_API_KEY)
