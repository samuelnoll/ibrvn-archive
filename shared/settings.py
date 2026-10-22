import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_GOLD_DB_PATH = PROJECT_ROOT / "data" / "gold" / "archive.db"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "data" / "exports"
DEFAULT_AUDIO_RAW_DIR = PROJECT_ROOT / "data" / "audio" / "raw"
DEFAULT_STUDY_RESOURCE_RAW_DIR = PROJECT_ROOT / "data" / "resource" / "raw"

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

AUDIO_RAW_DIR = Path(
    os.getenv("ARCHIVE_AUDIO_RAW_DIR", str(DEFAULT_AUDIO_RAW_DIR))
)

STUDY_RESOURCE_RAW_DIR = Path(
    os.getenv(
        "ARCHIVE_STUDY_RESOURCE_RAW_DIR",
        str(DEFAULT_STUDY_RESOURCE_RAW_DIR),
    ) or str(DEFAULT_STUDY_RESOURCE_RAW_DIR)
)

AI_BASE_URL = os.getenv(
    "ARCHIVE_AI_BASE_URL",
    "http://homelab-ai-api:8100",
).rstrip("/")
AI_TIMEOUT_SECONDS = int(
    os.getenv("ARCHIVE_AI_TIMEOUT_SECONDS", "7200")
)

OPENAI_API_KEY = os.getenv("ARCHIVE_OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv(
    "ARCHIVE_OPENAI_BASE_URL",
    "https://api.openai.com/v1",
).rstrip("/")
OPENAI_MODEL = os.getenv("ARCHIVE_OPENAI_MODEL", "chat-latest").strip()
OPENAI_TIMEOUT_SECONDS = int(
    os.getenv("ARCHIVE_OPENAI_TIMEOUT_SECONDS", str(AI_TIMEOUT_SECONDS))
)

EMAIL_SMTP_HOST = os.getenv("ARCHIVE_EMAIL_SMTP_HOST", "").strip()
EMAIL_SMTP_PORT = int(os.getenv("ARCHIVE_EMAIL_SMTP_PORT", "587"))
EMAIL_SMTP_USER = os.getenv("ARCHIVE_EMAIL_SMTP_USER", "").strip()
EMAIL_SMTP_PASSWORD = os.getenv("ARCHIVE_EMAIL_SMTP_PASSWORD", "")
EMAIL_SMTP_USE_TLS = os.getenv(
    "ARCHIVE_EMAIL_SMTP_USE_TLS",
    "true",
).strip().lower() in {"1", "true", "yes", "y", "on"}
EMAIL_FROM = os.getenv("ARCHIVE_EMAIL_FROM", "").strip()
EMAIL_TO = os.getenv("ARCHIVE_EMAIL_TO", "").strip()

LOCAL_TIMEZONE = os.getenv(
    "ARCHIVE_LOCAL_TIMEZONE",
    "America/Sao_Paulo",
).strip()

WHATSAPP_SCHEDULER_BASE_URL = os.getenv(
    "ARCHIVE_WHATSAPP_SCHEDULER_BASE_URL",
    "",
).rstrip("/")
WHATSAPP_SCHEDULER_TIMEOUT_SECONDS = int(
    os.getenv("ARCHIVE_WHATSAPP_SCHEDULER_TIMEOUT_SECONDS", "120")
)
WHATSAPP_CRITIQUE_TARGET_TYPE = os.getenv(
    "ARCHIVE_WHATSAPP_CRITIQUE_TARGET_TYPE",
    "group",
).strip()
WHATSAPP_CRITIQUE_TARGET_VALUE = os.getenv(
    "ARCHIVE_WHATSAPP_CRITIQUE_TARGET_VALUE",
    "",
).strip()
WHATSAPP_CRITIQUE_TARGET_LABEL = os.getenv(
    "ARCHIVE_WHATSAPP_CRITIQUE_TARGET_LABEL",
    "Critica da pregacao",
).strip()
