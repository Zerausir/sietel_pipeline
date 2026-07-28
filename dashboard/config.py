from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

load_dotenv()


def _require_env(name: str) -> str:
    """
    Mismo patrón que scripts/config.py de sietel_pipeline: falla explícito
    si falta una variable requerida, en vez de conectar silenciosamente con
    un valor vacío (ver hallazgo de la validación profesional anterior --
    el config.py anterior de este dashboard usaba os.getenv(..., "") para
    DB_PASSWORD, lo que permitía una conexión con contraseña vacía sin
    ningún error).
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno requerida: {name}. "
            f"Revisa el .env del contenedor."
        )
    return value


@dataclass(frozen=True)
class Settings:
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8050"))
    # Default FALSE deliberado -- el .env.example anterior traía "true".
    # Con Flask-Login activo, un debugger de Werkzeug expuesto junto a
    # sesiones autenticadas es un riesgo serio, no cosmético.
    app_debug: bool = os.getenv("APP_DEBUG", "false").lower() in {"1", "true", "yes", "si", "sí"}

    # Firma las cookies de sesión de Flask-Login. Generar una vez con:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    # y guardarla solo en el .env del contenedor -- nunca en Git.
    secret_key: str = os.getenv("SECRET_KEY", "")

    # ── Conexión de LECTURA analítica: rol dashboard_lector, solo mart.* ──
    mart_pg_host: str = os.getenv("MART_PG_HOST", "")
    mart_pg_port: int = int(os.getenv("MART_PG_PORT", "5432"))
    mart_pg_database: str = os.getenv("MART_PG_DATABASE", "sietel_analitico")
    mart_pg_user: str = os.getenv("MART_PG_USER", "dashboard_lector")
    mart_pg_password: str = os.getenv("MART_PG_PASSWORD", "")

    # ── Conexión de AUTENTICACIÓN: rol dashboard_auth, solo auth.usuarios_dashboard ──
    auth_pg_host: str = os.getenv("AUTH_PG_HOST", "")
    auth_pg_port: int = int(os.getenv("AUTH_PG_PORT", "5432"))
    auth_pg_database: str = os.getenv("AUTH_PG_DATABASE", "sietel_analitico")
    auth_pg_user: str = os.getenv("AUTH_PG_USER", "dashboard_auth")
    auth_pg_password: str = os.getenv("AUTH_PG_PASSWORD", "")

    cache_timeout: int = int(os.getenv("CACHE_TIMEOUT", "300"))

    def mart_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=_require_env("MART_PG_USER"),
            password=_require_env("MART_PG_PASSWORD"),
            host=_require_env("MART_PG_HOST"),
            port=self.mart_pg_port,
            database=self.mart_pg_database,
        )

    def auth_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=_require_env("AUTH_PG_USER"),
            password=_require_env("AUTH_PG_PASSWORD"),
            host=_require_env("AUTH_PG_HOST"),
            port=self.auth_pg_port,
            database=self.auth_pg_database,
        )


settings = Settings()

if not settings.secret_key:
    raise RuntimeError(
        "Falta SECRET_KEY en el entorno. Generar una vez con: "
        "python -c \"import secrets; print(secrets.token_hex(32))\" "
        "y guardarla en el .env del contenedor."
    )
