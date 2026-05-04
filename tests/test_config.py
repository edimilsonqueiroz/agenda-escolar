"""
Testes de configuração (app/config.py).

Cobre:
- _resolve_database_uri em desenvolvimento (padrão SQLite)
- _resolve_database_uri em desenvolvimento com DATABASE_URL
- _resolve_database_uri em produção SEM variáveis → RuntimeError esperado
- _resolve_database_uri em produção COM DATABASE_URL → passa
- _resolve_database_uri em produção com fallback habilitado explicitamente
- _normalize_database_url converte postgres:// → postgresql://
"""
import os
import importlib

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(env_overrides: dict) -> str:
    """
    Executa _resolve_database_uri() com variáveis de ambiente substituídas.
    Limpa as variáveis relevantes antes para evitar vazamento entre testes.
    """
    relevant_keys = [
        "FLASK_ENV",
        "DATABASE_URL",
        "PRODUCTION_DATABASE_URL",
        "DEVELOPMENT_DATABASE_URL",
        "ALLOW_INSECURE_PRODUCTION_DB_FALLBACK",
        "PRODUCTION_DATABASE_FALLBACK_URL",
    ]
    original = {k: os.environ.get(k) for k in relevant_keys}
    try:
        for k in relevant_keys:
            os.environ.pop(k, None)
        os.environ.update(env_overrides)

        # Recarrega o módulo para re-executar _resolve_database_uri como função pura
        import app.config as cfg_module
        importlib.reload(cfg_module)
        return cfg_module._resolve_database_uri()
    finally:
        for k in relevant_keys:
            os.environ.pop(k, None)
        for k, v in original.items():
            if v is not None:
                os.environ[k] = v
        # Recarrega para deixar o módulo no estado original (desenvolvimento)
        importlib.reload(cfg_module)


# ---------------------------------------------------------------------------
# Desenvolvimento
# ---------------------------------------------------------------------------

class TestDevelopmentConfig:
    def test_default_is_sqlite(self):
        uri = _resolve({})
        assert uri == "sqlite:///agenda_escolar.db"

    def test_respects_database_url(self):
        uri = _resolve({"DATABASE_URL": "postgresql://user:pass@host/dev"})
        assert uri == "postgresql://user:pass@host/dev"

    def test_respects_development_database_url(self):
        uri = _resolve({"DEVELOPMENT_DATABASE_URL": "sqlite:///custom_dev.db"})
        assert uri == "sqlite:///custom_dev.db"

    def test_database_url_takes_precedence_over_dev_url(self):
        uri = _resolve({
            "DATABASE_URL": "postgresql://primary/db",
            "DEVELOPMENT_DATABASE_URL": "sqlite:///secondary.db",
        })
        assert "primary" in uri


# ---------------------------------------------------------------------------
# Produção
# ---------------------------------------------------------------------------

class TestProductionConfig:
    def test_raises_without_db_url(self):
        with pytest.raises(RuntimeError, match="Production requires"):
            _resolve({"FLASK_ENV": "production"})

    def test_accepts_database_url(self):
        uri = _resolve({
            "FLASK_ENV": "production",
            "DATABASE_URL": "postgresql://prod:pass@host/db",
        })
        assert uri == "postgresql://prod:pass@host/db"

    def test_accepts_production_database_url(self):
        uri = _resolve({
            "FLASK_ENV": "production",
            "PRODUCTION_DATABASE_URL": "postgresql://prod2:x@host2/db2",
        })
        assert "prod2" in uri

    def test_fallback_allowed_with_explicit_flags(self):
        uri = _resolve({
            "FLASK_ENV": "production",
            "ALLOW_INSECURE_PRODUCTION_DB_FALLBACK": "1",
            "PRODUCTION_DATABASE_FALLBACK_URL": "postgresql://fallback/db",
        })
        assert "fallback" in uri

    def test_fallback_not_used_without_flag(self):
        with pytest.raises(RuntimeError):
            _resolve({
                "FLASK_ENV": "production",
                "PRODUCTION_DATABASE_FALLBACK_URL": "postgresql://fallback/db",
                # sem ALLOW_INSECURE_PRODUCTION_DB_FALLBACK
            })


# ---------------------------------------------------------------------------
# Normalização de URL
# ---------------------------------------------------------------------------

class TestNormalizeDatabaseUrl:
    def test_postgres_scheme_is_replaced(self):
        from app.config import _normalize_database_url
        result = _normalize_database_url("postgres://user:pass@host/db")
        assert result.startswith("postgresql://")

    def test_postgresql_scheme_is_unchanged(self):
        from app.config import _normalize_database_url
        url = "postgresql://user:pass@host/db"
        assert _normalize_database_url(url) == url

    def test_sqlite_url_is_unchanged(self):
        from app.config import _normalize_database_url
        url = "sqlite:///local.db"
        assert _normalize_database_url(url) == url
