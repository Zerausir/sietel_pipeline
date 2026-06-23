"""
DAG: sietel_usuarios_cuentas_pipeline

Orquesta la carga del módulo analítico "Usuarios y Cuentas":
  1. Carga/actualiza las dimensiones versionadas (ISP, PermisoVAgregado)
     -- SCD Tipo 2, una sola vez por corrida.
  2. Carga los hechos (VAReporteUsuariosCuentas + geografía) un año a la
     vez, usando dynamic task mapping para que cada año sea una task
     independiente, visible y reintentable por separado en la UI de Airflow.

Para la carga histórica inicial (2011-2026), correr este DAG una vez con
todos los años. Para operación regular (periodicidad mensual, ver decisión
de diseño), el DAG se programa con schedule mensual y se ajusta el rango de
años a [año_actual] únicamente -- ver variable AIRFLOW_VAR_ANIOS_A_CARGAR.
"""
from datetime import datetime, timedelta
import logging
import os
import sys

# Airflow 3.x: los decoradores @dag/@task y Variable se importan desde
# airflow.sdk, que es la interfaz pública estable para autores de DAGs.
# Los import paths legacy (airflow.decorators, airflow.models.Variable)
# quedaron deprecados y serán removidos en una versión futura.
from airflow.sdk import dag, task, Variable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

logger = logging.getLogger(__name__)

ANIO_INICIO_HISTORICO = 2011
ANIO_FIN_HISTORICO = 2026

default_args = {
    "owner": "equipo_analitica_sietel",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="sietel_usuarios_cuentas_pipeline",
    description="Carga SQL Server SIETEL -> PostgreSQL analítico, módulo Usuarios y Cuentas",
    default_args=default_args,
    schedule="@monthly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["sietel", "arcotel", "usuarios_cuentas"],
)
def sietel_usuarios_cuentas_pipeline():
    @task
    def aplicar_esquema():
        """
        Aplica sql/01_ddl_postgres.sql contra la base analítica (que ya
        debe existir, ej. "sietel_analitico"). Idempotente: si las tablas
        ya existen y tienen datos, no las destruye ni las recrea -- las
        cláusulas IF NOT EXISTS / CREATE OR REPLACE VIEW del propio DDL
        garantizan esto.
        """
        from aplicar_esquema import aplicar_esquema as _aplicar_esquema
        _aplicar_esquema()

    @task
    def cargar_dimensiones():
        from cargar_dimensiones import cargar_dim_isp, cargar_dim_permiso_va_agregado
        cargar_dim_isp()
        cargar_dim_permiso_va_agregado()

    @task
    def obtener_anios_a_cargar() -> list[int]:
        """
        Determina qué años cargar en esta corrida.

        - Variable de Airflow "sietel_anios_a_cargar" = "historico": carga
          todo el rango 2011-2026 (usar solo para la carga inicial).
        - Cualquier otro valor (o ausencia de la variable): carga únicamente
          el año en curso, comportamiento esperado para corridas mensuales
          regulares.
        """
        modo = Variable.get("sietel_anios_a_cargar", default="mensual")
        if modo == "historico":
            anios = list(range(ANIO_INICIO_HISTORICO, ANIO_FIN_HISTORICO + 1))
            logger.info("Modo histórico: cargando años %s", anios)
            return anios
        anio_actual = datetime.now().year
        logger.info("Modo mensual: cargando solo año %s", anio_actual)
        return [anio_actual]

    @task
    def cargar_hechos_de_anio(anio: int):
        from cargar_hechos_anio import cargar_hechos_anio
        cargar_hechos_anio(anio)

    esquema = aplicar_esquema()
    dimensiones = cargar_dimensiones()
    anios = obtener_anios_a_cargar()
    hechos = cargar_hechos_de_anio.expand(anio=anios)

    esquema >> dimensiones >> hechos


sietel_usuarios_cuentas_pipeline()
