from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import settings


@lru_cache(maxsize=1)
def get_mart_engine() -> Engine:
    """
    Engine de solo lectura -- rol dashboard_lector, esquema mart únicamente.

    AJUSTE (22-ago-2026, tras subir a 4 workers gthread en docker/Dockerfile):
    pool_size=5 + max_overflow=10 por PROCESO significaba hasta 15 conexiones
    solo de este engine por worker -- con 4 workers, hasta 60 en el peor
    caso, sumado a las de get_auth_engine(). Confirmado en VM1
    (22-ago-2026): max_connections=100, 24 en uso por el resto de sistemas
    (Airflow, samm_pipeline, etc.) -- ANTES de que este dashboard abriera
    una sola conexión. Reducido a un techo que deja margen real sin tocar
    max_connections de PostgreSQL (eso afectaría a TODO lo que corre en esa
    instancia, y exige reiniciar el servidor -- un cambio de infraestructura
    compartida, no algo que decidir desde aquí).
    """
    return create_engine(
        settings.mart_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=3,
        max_overflow=5,
        connect_args={"connect_timeout": 10},
    )


@lru_cache(maxsize=1)
def get_auth_engine() -> Engine:
    """
    Engine separado -- rol dashboard_auth, únicamente auth.usuarios_dashboard.
    Deliberadamente NO es el mismo engine que get_mart_engine(): son roles de
    PostgreSQL distintos con permisos distintos (ver sql/03_ddl_auth.sql).

    AJUSTE (22-ago-2026): mismo motivo que get_mart_engine() -- ver ese
    docstring. auth.usuarios_dashboard se consulta solo en login/logout, no
    en cada callback de datos, así que el volumen real de conexiones
    concurrentes aquí es mucho menor -- pool más chico todavía.
    """
    return create_engine(
        settings.auth_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=2,
        max_overflow=2,
        connect_args={"connect_timeout": 10},
    )


def validate_mart() -> dict[str, bool]:
    required = [
        "mart.vw_dashboard_evolucion",
        "mart.vw_dashboard_velocidades",
        "mart.vw_dashboard_participacion",
        "mart.vw_dashboard_ihh",
        "mart.vw_dashboard_filtros_geograficos",
        "mart.dim_periodo",
    ]

    sql = text(
        """
        SELECT :object_name AS object_name,
               TO_REGCLASS(:object_name) IS NOT NULL AS exists
        """
    )

    result: dict[str, bool] = {}
    with get_mart_engine().connect() as connection:
        for object_name in required:
            row = connection.execute(sql, {"object_name": object_name}).mappings().one()
            result[object_name] = bool(row["exists"])
    return result


def validate_auth() -> bool:
    """Confirma que auth.usuarios_dashboard existe y es alcanzable con dashboard_auth."""
    sql = text("SELECT TO_REGCLASS('auth.usuarios_dashboard') IS NOT NULL AS existe")
    with get_auth_engine().connect() as connection:
        return bool(connection.execute(sql).mappings().one()["existe"])
