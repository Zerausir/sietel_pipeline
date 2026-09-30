"""
DAG: sietel_detector_cambios (30-sep-2026)

Revisa todos los días si SIETEL (SQL Server) tiene información nueva o
corregida y, solo si la hay, dispara sietel_usuarios_cuentas_pipeline con
los meses afectados en conf ({"periodos": [[anio, mes], ...]}): se recargan
solo esos meses, no el año. Si solo cambiaron formularios, "periodos" va
vacío y la corrida solo recarga el snapshot de formularios. Ese DAG, al
terminar, dispara sietel_mart_pipeline, que reconstruye capa2 y mart
completos.

  1. detectar_cambios_sietel — compara la huella de SIETEL por
                               (anio, periodoNumero) contra
                               staging.huella_fuente (ver
                               scripts/detectar_cambios.py).
  2. hay_cambios             — corta el DAG si no cambió nada.
  3. disparar_carga          — dispara la carga de esos meses.

REQUIERE:
  - staging.huella_fuente sembrada (python scripts/detectar_cambios.py
    --sembrar); vacía, la tarea 1 falla a
    propósito en vez de disparar una recarga histórica completa.
  - sietel_usuarios_cuentas_pipeline y sietel_mart_pipeline DESPAUSADOS.
Se crea pausado (DAGS_ARE_PAUSED_AT_CREATION): despausarlo activa la
revisión diaria.
"""
from datetime import datetime, timedelta
import logging
import os
import sys

from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sdk import dag, task

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

logger = logging.getLogger(__name__)

default_args = {
    "owner": "equipo_analitica_sietel",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}


@dag(
    dag_id="sietel_detector_cambios",
    description="Detecta información nueva o corregida en SIETEL y dispara la carga de los años afectados",
    default_args=default_args,
    schedule="0 6 * * *",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,
    tags=["sietel", "arcotel", "deteccion"],
)
def sietel_detector_cambios():
    @task
    def detectar_cambios_sietel() -> dict:
        from detectar_cambios import detectar_cambios
        return detectar_cambios()

    @task.short_circuit
    def hay_cambios(cambios: dict) -> bool:
        return bool(cambios["periodos"]) or cambios["formularios"]

    @task
    def periodos(cambios: dict) -> list[list[int]]:
        return cambios["periodos"]

    cambios = detectar_cambios_sietel()

    disparar_carga = TriggerDagRunOperator(
        task_id="disparar_carga",
        trigger_dag_id="sietel_usuarios_cuentas_pipeline",
        conf={"periodos": periodos(cambios), "origen": "detector"},
        wait_for_completion=False,
    )

    hay_cambios(cambios) >> disparar_carga


sietel_detector_cambios()
