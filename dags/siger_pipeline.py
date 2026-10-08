"""
DAG: siger_pipeline

Réplica certificada de SIGER_V3 (títulos habilitantes, concesionarios y
facturación de espectro) en el esquema siger de sietel_analitico, y cruce
con OBTEL en calidad:
  1. aplicar_esquema_siger — sql/12_ddl_siger.sql como siger_user
                             (idempotente) + universo SAI.
  2. cargar_servicios      — snapshot por reemplazo de dbo.SERVICIO_TH.
  3. cargar_concesionarios — snapshot de dbo.VISTA_CONCESIONARIOS (+ RUC resuelto).
  4. cargar_titulos        — snapshot de dbo.TITULO_HABILITANTE (+ contrato_key).
  5. cargar_facturacion    — snapshot de dbo.NR_PARAMETROS_FACTURACION
                             (~2,5 M filas; necesita los títulos para tipo_enlace).
  6. validar_siger         — conteo + MD5 en ambas direcciones contra SIGER,
                             accesos LOPDP y métricas de referencia.
  7. construir_cruce_obtel — calidad.hallazgos_siger_obtel (como mart_user).
Cada carga certifica su propio snapshot ANTES del COMMIT y revierte si algo
no cuadra (ver siger/cargar_siger.py).

DETECCIÓN DE CAMBIOS (08-oct-2026, siger/huella_siger.py): cada carga compara
una huella barata de SIGER (conteo + CHECKSUM_AGG) con la del último
snapshot; si no cambió, la tabla no se recarga (unos segundos en vez de
~12 min para facturación). Facturación se recarga también si se recargaron
los títulos (tipo_enlace depende de ellos). validar_siger corre solo si algo
se recargó (hubo_recargas) y solo sobre esas tablas; el cruce con OBTEL
corre siempre (OBTEL cambia aunque SIGER no). Los domingos
(DIA_RECARGA_COMPLETA) se recargan y certifican las 4 tablas igual.

DAG INDEPENDIENTE de sietel_usuarios_cuentas_pipeline / sietel_mart_pipeline
a propósito: otro servidor (192.168.129.40), otras credenciales
(SIGER_SQLSERVER_*, SIGER_PG_*), otra cadencia. Un fallo de SIGER no
bloquea SIETEL, y este DAG no dispara ni modifica los de SIETEL.

Diario a las 02:00 (schedule="0 2 * * *"): termina antes de que arranque
sietel_detector_cambios (06:00) y su cadena de carga, para no competir por
el PostgreSQL analítico. El cruce usa el OBTEL cargado hasta el día anterior.

conf DEL DAG RUN (opcional, solo en disparos manuales):
  {"forzar_recarga": true} → recarga las 4 tablas aunque la huella no haya
      cambiado (p. ej. tras cambiar siger/reglas.py).
  {"permitir_caida": ["siger_facturacion"]} → omite la protección de caída
      > 20 % SOLO para esas tablas (tipo_carga), tras revisar que es real.
  {"permitir_caida": true}                   → para todas.

execution_timeout explícito por tarea (no existe un timeout global válido:
AIRFLOW__CORE__TASK_TIMEOUT no es una opción de Airflow). Valores iniciales
con margen; ajustar con las duraciones medidas en staging.control_cargas.
"""
from datetime import datetime, timedelta
import logging
import os
import sys

from airflow.sdk import dag, get_current_context, task

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "siger"))

logger = logging.getLogger(__name__)

default_args = {
    "owner": "equipo_analitica_sietel",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _permitir_caida(tipo_carga: str) -> bool:
    conf = get_current_context()["dag_run"].conf or {}
    valor = conf.get("permitir_caida", False)
    permitido = valor is True or (isinstance(valor, list) and tipo_carga in valor)
    if permitido:
        logger.warning("permitir_caida activo para %s (dag_run.conf): se omite la protección de caída.",
                       tipo_carga)
    return permitido


def _forzar_recarga() -> bool:
    from config_siger import DIA_RECARGA_COMPLETA
    ctx = get_current_context()
    if (ctx["dag_run"].conf or {}).get("forzar_recarga") is True:
        logger.warning("forzar_recarga activo (dag_run.conf): se recarga aunque no haya cambios.")
        return True
    fecha = getattr(ctx["dag_run"], "run_after", None) or ctx.get("logical_date")
    if fecha is not None and fecha.weekday() == DIA_RECARGA_COMPLETA:
        logger.info("Día de recarga completa semanal: se recarga aunque no haya cambios.")
        return True
    return False


def _cargar(clave: str, dependencia_recargada: bool = False) -> dict:
    from cargar_siger import TABLAS, cargar_tabla
    return cargar_tabla(clave, permitir_caida=_permitir_caida(TABLAS[clave].tipo_carga),
                        forzar=_forzar_recarga(), dependencia_recargada=dependencia_recargada)


@dag(
    dag_id="siger_pipeline",
    description="Réplica certificada SIGER_V3 → esquema siger y cruce con OBTEL en calidad",
    default_args=default_args,
    schedule="0 2 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    tags=["siger", "arcotel", "titulos_habilitantes"],
)
def siger_pipeline():
    @task(execution_timeout=timedelta(minutes=10))
    def aplicar_esquema_siger():
        """Aplica sql/12_ddl_siger.sql como siger_user y sincroniza el universo SAI."""
        from aplicar_esquema_siger import aplicar_esquema_siger as _run
        _run()

    @task(execution_timeout=timedelta(minutes=10))
    def cargar_servicios() -> dict:
        return _cargar("servicios")

    @task(execution_timeout=timedelta(minutes=20))
    def cargar_concesionarios() -> dict:
        return _cargar("concesionarios")

    @task(execution_timeout=timedelta(minutes=20))
    def cargar_titulos() -> dict:
        return _cargar("titulos")

    @task(execution_timeout=timedelta(hours=3))
    def cargar_facturacion(titulos: dict) -> dict:
        return _cargar("facturacion", dependencia_recargada=titulos["recargada"])

    # Si ninguna tabla se recargó, salta validar_siger (no hay snapshot nuevo
    # que certificar). ignore_downstream_trigger_rules=False: solo salta la
    # tarea inmediata, el cruce (none_failed) sigue corriendo.
    @task.short_circuit(ignore_downstream_trigger_rules=False)
    def hubo_recargas(resultados: list[dict]) -> bool:
        recargadas = [r["clave"] for r in resultados if r["recargada"]]
        logger.info("Tablas recargadas: %s", recargadas or "ninguna (SIGER sin cambios)")
        return bool(recargadas)

    @task(execution_timeout=timedelta(hours=3))
    def validar_siger(resultados: list[dict]):
        from validar_siger import validar_siger as _run
        _run([r["clave"] for r in resultados if r["recargada"]])

    # none_failed: corre aunque validar_siger se haya saltado (SIGER sin
    # cambios, pero OBTEL pudo cambiar); no corre si alguna carga o la
    # validación fallaron.
    @task(execution_timeout=timedelta(minutes=20), trigger_rule="none_failed")
    def construir_cruce_obtel():
        """Hallazgos SIGER ↔ OBTEL en calidad.hallazgos_siger_obtel (como mart_user)."""
        from construir_cruce_obtel import construir_cruce_obtel as _run
        _run(dry_run=False)

    esquema = aplicar_esquema_siger()
    servicios, concesionarios, titulos = cargar_servicios(), cargar_concesionarios(), cargar_titulos()
    cargas = [servicios, concesionarios, titulos]
    facturacion = cargar_facturacion(titulos)
    resultados = [servicios, concesionarios, titulos, facturacion]
    validacion = validar_siger(resultados)
    cruce = construir_cruce_obtel()

    esquema >> cargas >> facturacion >> hubo_recargas(resultados) >> validacion >> cruce


siger_pipeline()
