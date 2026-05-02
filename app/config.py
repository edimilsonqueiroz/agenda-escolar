import os
from datetime import timedelta


TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _normalize_database_url(database_url: str) -> str:
    # Heroku-style URLs may come as postgres:// and need SQLAlchemy-compatible prefix.
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url


def _resolve_database_uri() -> str:
    env = os.getenv("FLASK_ENV", "development").lower()

    if env == "production":
        db_url = os.getenv("DATABASE_URL") or os.getenv("PRODUCTION_DATABASE_URL")
        if db_url:
            return _normalize_database_url(db_url)

        fallback_allowed = os.getenv("ALLOW_INSECURE_PRODUCTION_DB_FALLBACK", "").strip().lower() in TRUTHY_VALUES
        fallback_url = os.getenv("PRODUCTION_DATABASE_FALLBACK_URL", "").strip()
        if fallback_allowed and fallback_url:
            return _normalize_database_url(fallback_url)

        raise RuntimeError(
            "Production requires DATABASE_URL or PRODUCTION_DATABASE_URL. "
            "If you really need a temporary fallback, set "
            "ALLOW_INSECURE_PRODUCTION_DB_FALLBACK=1 and PRODUCTION_DATABASE_FALLBACK_URL."
        )

    # Development defaults to local SQLite for zero-setup onboarding.
    dev_url = os.getenv("DATABASE_URL") or os.getenv("DEVELOPMENT_DATABASE_URL")
    if dev_url:
        return _normalize_database_url(dev_url)
    return "sqlite:///agenda_escolar.db"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = _resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB (suporta PDFs de trabalhos)
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    WTF_CSRF_TIME_LIMIT = 60 * 30  # 30 minutos
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "200/day;50/hour")
    RATELIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
