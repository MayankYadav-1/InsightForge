import os
from pathlib import Path


DATA_DIR = Path(os.getenv("INSIGHTFORGE_DATA_DIR", "./data")).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("INSIGHTFORGE_MAX_UPLOAD_MB", "25")) * 1024 * 1024
MAX_ROWS = int(os.getenv("INSIGHTFORGE_MAX_ROWS", "250000"))
MAX_COLUMNS = int(os.getenv("INSIGHTFORGE_MAX_COLUMNS", "250"))
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
