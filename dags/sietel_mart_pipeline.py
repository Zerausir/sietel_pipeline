"""
DAG: sietel_mart_pipeline

Orquesta el refresco del mart analítico consumido por el dashboard:
  1. detectar_conflictos_peva — detecta y clasifica RUC con múltiples PEVA,
                                 resuelve automáticamente el Grupo A.
  2. construir_capa2          — reconstruye capa2.lineas_dedicadas_consolidado
                                 (reemplaza al antiguo Datos.ipynb).
  3. aplicar_capa3            — aplica sql/02_ddl_mart.sql completo (mart.*).

Manual (schedule=None), mismo criterio que sietel_usuarios_cuentas_pipeline.
Se dispara cuando se quiere refrescar el dashboard, no en cada carga base.

REQUIERE: que los roles de PostgreSQL (mart_user, dashboard_lector,
dashboard_auth, calidad_lector, calidad_revisor) y los esquemas base
(calidad, capa2, mart, auth) ya existan -- ver "Creación de roles y
usuarios de PostgreSQL — sietel_pipeline.docx" y sql/00_roles_mart.sql /
sql/03_ddl_auth.sql / sql/04_ddl_calidad.sql. Este DAG NO crea roles ni
esquemas nuevos, solo actualiza los datos dentro de ellos.

Variables de entorno MART_USER_USER / MART_USER_PASSWORD deben estar
inyectadas al contenedor de Airflow (ver docker/docker-compose.yml) y el
directorio mart/ debe estar montado en /opt/airflow/mart -- ninguna de las
dos cosas existía antes de este DAG; se agregaron junto con él.
"""
from datetime import datetime, timedelta
import logging
import os
import sys

from airflow.sdk import dag, task

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mart"))

logger = logging.getLogger(__name__)

default_args = {
    "owner": "equipo_analitica_sietel",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="sietel_mart_pipeline",
    description="Detecta conflictos RUC/PEVA, reconstruye capa2 y aplica Capa 3 (mart.*) para el dashboard",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=["sietel", "mart", "dashboard"],
)
def sietel_mart_pipeline():
    @task
    def detectar_conflictos_peva():
        """Detecta y clasifica RUC con múltiples PEVA; resuelve el Grupo A automáticamente."""
        from detectar_conflictos_peva import detectar_conflictos_peva as _run
        _run(dry_run=False)

    @task
    def construir_capa2():
        """Reconstruye capa2.lineas_dedicadas_consolidado desde analitico.v_lineas_dedicadas_resumen."""
        from construir_capa2 import construir_capa2 as _run
        _run(dry_run=False)

    @task
    def aplicar_capa3():
        """Aplica sql/02_ddl_mart.sql completo (Capa 3: mart.*)."""
        from aplicar_capa3 import aplicar as _run
        _run()

    deteccion = detectar_conflictos_peva()
    construccion = construir_capa2()
    aplicacion = aplicar_capa3()

    deteccion >> construccion >> aplicacion


sietel_mart_pipeline()
