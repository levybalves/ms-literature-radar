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

# Busca principal por fonte.
BASE_QUERY = '("multiple sclerosis"[MeSH Terms] OR "multiple sclerosis"[Title/Abstract])'
DISCOVERY_QUERY = os.getenv("DISCOVERY_QUERY", "multiple sclerosis").strip() or "multiple sclerosis"

# NCBI / PubMed.
PUBMED_EMAIL = os.getenv("PUBMED_EMAIL", "").strip()
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "").strip()
PUBMED_DISCOVERY_ENABLED = os.getenv("PUBMED_DISCOVERY_ENABLED", "true").lower() in {"1", "true", "yes"}
PUBMED_RETMAX = int(os.getenv("PUBMED_RETMAX", "250"))
PUBMED_BATCH_SIZE = min(int(os.getenv("PUBMED_BATCH_SIZE", "150")), 200)

# Crossref.
CROSSREF_DISCOVERY_ENABLED = os.getenv("CROSSREF_DISCOVERY_ENABLED", "true").lower() in {"1", "true", "yes"}
CROSSREF_ENABLED = os.getenv("CROSSREF_ENABLED", "true").lower() in {"1", "true", "yes"}
CROSSREF_RETMAX = int(os.getenv("CROSSREF_RETMAX", "250"))
CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL", PUBMED_EMAIL).strip()
CROSSREF_DISCOVERY_INCLUDE_CREATED = os.getenv("CROSSREF_DISCOVERY_INCLUDE_CREATED", "true").lower() in {"1", "true", "yes"}

# Europe PMC.
EUROPE_PMC_DISCOVERY_ENABLED = os.getenv("EUROPE_PMC_DISCOVERY_ENABLED", "true").lower() in {"1", "true", "yes"}
EUROPE_PMC_ENABLED = os.getenv("EUROPE_PMC_ENABLED", "true").lower() in {"1", "true", "yes"}
EUROPE_PMC_RETMAX = int(os.getenv("EUROPE_PMC_RETMAX", "250"))


# Filtro de elegibilidade para esclerose múltipla.
MS_ELIGIBILITY_ENABLED = os.getenv("MS_ELIGIBILITY_ENABLED", "true").lower() in {"1", "true", "yes"}
MS_HIGH_THRESHOLD = float(os.getenv("MS_HIGH_THRESHOLD", "9"))
MS_MODERATE_THRESHOLD = float(os.getenv("MS_MODERATE_THRESHOLD", "6"))
MS_STORE_PENDING = os.getenv("MS_STORE_PENDING", "true").lower() in {"1", "true", "yes"}
MS_REASSESS_ON_STARTUP = os.getenv("MS_REASSESS_ON_STARTUP", "true").lower() in {"1", "true", "yes"}

# Janelas e painel.
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "45"))
DEFAULT_VIEW_DAYS = int(os.getenv("DEFAULT_VIEW_DAYS", "5"))

# Enriquecimento. APIs estruturadas ficam ativadas por padrão; scraping HTML é opt-in.
ENRICHMENT_ENABLED = os.getenv("ENRICHMENT_ENABLED", "true").lower() in {"1", "true", "yes"}
PUBLISHER_HTML_ENABLED = os.getenv("PUBLISHER_HTML_ENABLED", "false").lower() in {"1", "true", "yes"}
ENRICHMENT_MAX_ARTICLES = max(0, int(os.getenv("ENRICHMENT_MAX_ARTICLES", "50")))
ENRICHMENT_TIMEOUT = max(5, int(os.getenv("ENRICHMENT_TIMEOUT", "20")))
ENRICHMENT_PAUSE_SECONDS = max(0.0, float(os.getenv("ENRICHMENT_PAUSE_SECONDS", "0.15")))
HTML_MAX_BYTES = max(100_000, int(os.getenv("HTML_MAX_BYTES", "2000000")))

# Aplicação.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5050"))
DEBUG = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}

TOOL_NAME = "ms_literature_radar"
