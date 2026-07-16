"""
DAG: sietel_usuarios_cuentas_pipeline

Orquesta la carga del módulo analítico "Usuarios y Cuentas — Internet Fijo":
  1. aplicar_esquema    — DDL idempotente contra PostgreSQL analítico.
  2. cargar_dimensiones — SCD Tipo 2: ISP y PermisoVAgregado.
  3. obtener_anios_a_cargar — determina qué años cargar en esta corrida.
  4. cargar_hechos_de_anio  — extracción agregada de dbo.VALineasDedicadas,
                              un año a la vez (dynamic task mapping).
  5. validar_carga      — certificación cruzada SQL Server vs PostgreSQL.

VARIABLE DE AIRFLOW "sietel_anios_a_cargar":
  "historico"  → carga todo el rango ANIO_INICIO_HISTORICO..ANIO_FIN_HISTORICO
  "2025"       → carga solo ese año específico (útil para pruebas)
  "2023,2024"  → carga esos años separados por coma
  ausente/otro → carga únicamente el año en curso (modo mensual regular)
"""
from datetime import datetime, timedelta
import logging
import os
import sys

from airflow.sdk import dag, task, Variable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

logger = logging.getLogger(__name__)

ANIO_INICIO_HISTORICO = 2011
ANIO_FIN_HISTORICO = 2025  # copia tiene datos hasta 2025; ajustar a 2026 en producción

default_args = {
    "owner": "equipo_analitica_sietel",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="sietel_usuarios_cuentas_pipeline",
    description="Carga SQL Server SIETEL → PostgreSQL analítico, módulo Usuarios y Cuentas",
    default_args=default_args,
    schedule="@monthly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["sietel", "arcotel", "usuarios_cuentas"],
)
def sietel_usuarios_cuentas_pipeline():
    @task
    def aplicar_esquema():
        """Aplica sql/01_ddl_postgres.sql de forma idempotente."""
        from aplicar_esquema import aplicar_esquema as _run
        _run()

    @task
    def cargar_dimensiones():
        from cargar_dimensiones import cargar_dim_isp, cargar_dim_permiso_va_agregado
        cargar_dim_isp()
        cargar_dim_permiso_va_agregado()

    @task
    def obtener_anios_a_cargar() -> list[int]:
        """
        Determina qué años cargar según la variable "sietel_anios_a_cargar":

          "historico"     → rango completo ANIO_INICIO_HISTORICO..ANIO_FIN_HISTORICO
          "2025"          → solo ese año
          "2023,2024,2025"→ lista de años separados por coma
          ausente / otro  → solo el año en curso (modo mensual regular)
        """
        valor = Variable.get("sietel_anios_a_cargar", default="mensual")

        if valor.strip().lower() == "historico":
            anios = list(range(ANIO_INICIO_HISTORICO, ANIO_FIN_HISTORICO + 1))
            logger.info("Modo histórico: cargando años %s", anios)
            return anios

        # Intentar interpretar como año(s) numérico(s): "2025" o "2023,2024,2025"
        try:
            partes = [p.strip() for p in valor.split(",") if p.strip()]
            anios = [int(p) for p in partes]
            if all(2000 <= a <= 2100 for a in anios):
                logger.info("Modo año(s) específico(s): cargando %s", anios)
                return anios
        except ValueError:
            pass

        # Fallback: año en curso
        anio_actual = datetime.now().year
        logger.info("Modo mensual: cargando solo año %s", anio_actual)
        return [anio_actual]

    @task
    def cargar_hechos_de_anio(anio: int):
        from cargar_hechos_anio import cargar_hechos_anio
        cargar_hechos_anio(anio)

    @task
    def validar_carga(anios: list[int]):
        from validar_carga import validar_anios
        validar_anios(anios)

    esquema = aplicar_esquema()
    dimensiones = cargar_dimensiones()
    anios = obtener_anios_a_cargar()
    hechos = cargar_hechos_de_anio.expand(anio=anios)
    validacion = validar_carga(anios)

    esquema >> dimensiones >> hechos >> validacion


sietel_usuarios_cuentas_pipeline()
