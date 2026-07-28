from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import settings


@lru_cache(maxsize=1)
def get_mart_engine() -> Engine:
    """Engine de solo lectura -- rol dashboard_lector, esquema mart únicamente."""
    return create_engine(
        settings.mart_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 10},
    )


@lru_cache(maxsize=1)
def get_auth_engine() -> Engine:
    """
    Engine separado -- rol dashboard_auth, únicamente auth.usuarios_dashboard.
    Deliberadamente NO es el mismo engine que get_mart_engine(): son roles de
    PostgreSQL distintos con permisos distintos (ver sql/03_ddl_auth.sql).
    """
    return create_engine(
        settings.auth_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=3,
        max_overflow=5,
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
