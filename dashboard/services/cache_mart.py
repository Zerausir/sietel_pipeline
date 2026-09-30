"""
dashboard/services/cache_mart.py — Vacía la caché cuando hay un mart nuevo (30-sep-2026).

Las consultas se memoizan hasta 1 h (services/queries.py) y ninguna corrida
del pipeline limpiaba la caché, así que un mart recién reconstruido podía
tardar hasta una hora en verse. sietel_mart_pipeline escribe la fecha de
cada reconstrucción en mart.control_version (sql/02_ddl_mart.sql, 17b);
aquí se compara contra la última versión vista y, si cambió, se vacía la
caché compartida (FileSystemCache, común a todos los workers de gunicorn).

La consulta a PostgreSQL se hace como mucho una vez por INTERVALO_SEGUNDOS
por proceso -- no en cada petición. La versión vista se guarda en la propia
caché, así un solo worker la vacía y los demás ven la versión nueva.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import text

from extensions import cache
from services.database import get_mart_engine

logger = logging.getLogger(__name__)

INTERVALO_SEGUNDOS = 60
CLAVE_VERSION = "mart_control_version"

_ultimo_chequeo = 0.0


def vaciar_cache_si_mart_cambio() -> None:
    global _ultimo_chequeo
    ahora = time.monotonic()
    if ahora - _ultimo_chequeo < INTERVALO_SEGUNDOS:
        return
    _ultimo_chequeo = ahora

    try:
        with get_mart_engine().connect() as conn:
            version = conn.execute(text("SELECT fecha_reconstruccion FROM mart.control_version")).scalar()
    except Exception:
        # Mart a medio reconstruir o tabla aún no creada: se sigue sirviendo
        # la caché actual y se reintenta en el siguiente intervalo.
        logger.warning("No se pudo leer mart.control_version; la caché no se revisa esta vez.", exc_info=True)
        return

    version = str(version)
    if cache.get(CLAVE_VERSION) != version:
        logger.info("Mart reconstruido (%s): se vacía la caché del dashboard.", version)
        cache.clear()
        cache.set(CLAVE_VERSION, version, timeout=0)
