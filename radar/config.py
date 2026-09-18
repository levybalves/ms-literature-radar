from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "radar.sqlite3"
TOPICS_PATH = BASE_DIR / "config" / "topics.yaml"

# Busca central. A janela temporal é enviada ao ESearch por mindate/maxdate.
BASE_QUERY = '("multiple sclerosis"[MeSH Terms] OR "multiple sclerosis"[Title/Abstract])'

PUBMED_EMAIL = os.getenv("PUBMED_EMAIL", "").strip()
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "").strip()
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "45"))
DEFAULT_VIEW_DAYS = int(os.getenv("DEFAULT_VIEW_DAYS", "5"))
PUBMED_RETMAX = int(os.getenv("PUBMED_RETMAX", "250"))
PUBMED_BATCH_SIZE = min(int(os.getenv("PUBMED_BATCH_SIZE", "150")), 200)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5000"))
DEBUG = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}

TOOL_NAME = "ms_literature_radar"
