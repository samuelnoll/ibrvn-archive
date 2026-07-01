import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_GOLD_DB_PATH = PROJECT_ROOT / "data" / "gold" / "archive.db"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "data" / "exports"

API_HOST = os.getenv("ARCHIVE_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("ARCHIVE_API_PORT", "8000"))

DATABASE_BACKEND = os.getenv("ARCHIVE_DATABASE_BACKEND", "sqlite").lower()
DATABASE_URL = os.getenv("ARCHIVE_DATABASE_URL", "")
DATABASE_HOST = os.getenv("ARCHIVE_DATABASE_HOST", "postgres")
DATABASE_PORT = int(os.getenv("ARCHIVE_DATABASE_PORT", "5432"))
DATABASE_NAME = os.getenv("ARCHIVE_DATABASE_NAME", "app")
DATABASE_USER = os.getenv("ARCHIVE_DATABASE_USER", "app")
DATABASE_PASSWORD = os.getenv("ARCHIVE_DATABASE_PASSWORD", "")

GOLD_DB_PATH = Path(
    os.getenv("ARCHIVE_GOLD_DB_PATH", str(DEFAULT_GOLD_DB_PATH))
)

LEGACY_SQLITE_PATH = Path(
    os.getenv("ARCHIVE_LEGACY_SQLITE_PATH", str(DEFAULT_GOLD_DB_PATH))
)

EXPORT_DIR = Path(
    os.getenv("ARCHIVE_EXPORT_DIR", str(DEFAULT_EXPORT_DIR))
)
