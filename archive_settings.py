import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_GOLD_DB_PATH = PROJECT_ROOT / "data" / "gold" / "archive.db"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "data" / "exports"

GOLD_DB_PATH = Path(
    os.getenv("ARCHIVE_GOLD_DB_PATH", str(DEFAULT_GOLD_DB_PATH))
)

EXPORT_DIR = Path(
    os.getenv("ARCHIVE_EXPORT_DIR", str(DEFAULT_EXPORT_DIR))
)

API_HOST = os.getenv("ARCHIVE_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("ARCHIVE_API_PORT", "8000"))
