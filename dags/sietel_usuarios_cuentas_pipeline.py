"""
DAG: sietel_usuarios_cuentas_pipeline

Orquesta la carga del módulo analítico "Usuarios y Cuentas — Internet Fijo":
  1. aplicar_esquema    — DDL idempotente contra PostgreSQL analítico.
  2. cargar_dimensiones — SCD Tipo 2: ISP y PermisoVAgregado.
  3. cargar_nodos_isp   — SCD Tipo 2: NodoISP (geografía de nodos de acceso;
                          dbo.NodoISP_Auxiliar excluida a propósito, ver
                          scripts/cargar_nodo_isp.py).
  3b. cargar_formularios_lineas — snapshot de dbo.VAFormularioLineasDedicadas
                          (incluye declaraciones "sin servicio", 28-sep-2026).
  4. obtener_periodos_a_cargar — determina qué años/meses cargar en esta corrida.
  5. cargar_hechos_de_anio  — extracción agregada de dbo.VALineasDedicadas,
                              un año a la vez (dynamic task mapping), solo
                              con los meses del lote.
  6. validar_carga      — certificación cruzada SQL Server vs PostgreSQL de
                          esos mismos meses.
  7. guardar_huella_fuente — registra en staging.huella_fuente la huella
                              de SIETEL tomada al inicio (tomar_huella_fuente),
                              solo para los meses cargados y certificados.
  8. disparar_mart_pipeline — dispara sietel_mart_pipeline si todo lo
                              anterior pasó (reconstruye las vistas de mart
                              que el paso 1 borra por CASCADE).

conf DEL DAG RUN (30-sep-2026), con prioridad sobre la variable:
  {"periodos": [[2025, 12], [2026, 3]]} → solo esos meses. Así lo dispara
                                          sietel_detector_cambios.
  {"anios": [2025, 2026]}                → esos años completos.

VARIABLE DE AIRFLOW "sietel_anios_a_cargar":
  "historico"  → carga todo el rango ANIO_INICIO_HISTORICO..ANIO_FIN_HISTORICO
  "2025"       → carga solo ese año específico (útil para pruebas)
  "2023,2024"  → carga esos años separados por coma
  ausente/otro → carga únicamente el año en curso (modo mensual regular)

NOTA (2026-07): ANIO_INICIO_HISTORICO / ANIO_FIN_HISTORICO ya NO se definen
en este archivo. Antes existían dos copias independientes (una aquí, otra
en scripts/config.py) que ya habían divergido (2025 vs 2026). Ahora
scripts/config.py es la única fuente de verdad; este DAG las importa de
forma perezosa dentro de la propia tarea, igual que el resto de los
imports de scripts/, para no encarecer el parseo periódico del DAG con las
dependencias de config.py (pyodbc, psycopg2, carga de .env).
"""
from datetime import datetime, timedelta
import logging
import os
import sys

from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sdk import dag, get_current_context, task, Variable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

logger = logging.getLogger(__name__)

default_args = {
    "owner": "equipo_analitica_sietel",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="sietel_usuarios_cuentas_pipeline",
    description="Carga SQL Server SIETEL → PostgreSQL analítico, módulo Usuarios y Cuentas",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    # Un disparo del detector mientras hay otra carga en curso queda en cola
    # en vez de correr en paralelo sobre las mismas tablas.
    max_active_runs=1,
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
    def cargar_nodos_isp():
        """SCD Tipo 2 de dbo.NodoISP. Tarea separada de cargar_dimensiones
        para aislar logs/reintentos -- ver scripts/cargar_nodo_isp.py para el
        motivo de excluir dbo.NodoISP_Auxiliar."""
        from cargar_nodo_isp import cargar_dim_nodo_isp
        cargar_dim_nodo_isp()

    @task
    def cargar_formularios_lineas():
        """Snapshot de dbo.VAFormularioLineasDedicadas (declaraciones 'sin
        servicio' incluidas) -- ver scripts/cargar_formularios_lineas.py."""
        from cargar_formularios_lineas import cargar_formularios_lineas as _run
        _run()

    @task
    def tomar_huella_fuente() -> list[dict]:
        """Huella de SIETEL ANTES de cargar: si el origen cambia durante la
        carga, la huella guardada queda vieja y el detector lo vuelve a ver."""
        from detectar_cambios import tomar_huella
        return tomar_huella()

    @task
    def obtener_periodos_a_cargar() -> list[dict]:
        """
        Determina qué cargar, como lotes [{"anio": 2026, "meses": [1, 2]}, ...]
        (uno por año, cada uno una tarea mapeada). En orden de prioridad:

          dag_run.conf["periodos"] → [[anio, mes], ...]: solo esos meses. Lo
                                     usa sietel_detector_cambios; puede venir
                                     vacío si solo cambiaron formularios.
          dag_run.conf["anios"]    → [2025, 2026]: esos años completos.
          variable "sietel_anios_a_cargar" (años completos):
            "historico"      → rango ANIO_INICIO_HISTORICO..ANIO_FIN_HISTORICO
            "2025"           → solo ese año
            "2023,2024,2025" → lista de años separados por coma
            ausente / otro   → solo el año en curso (modo mensual regular)

        ANIO_INICIO_HISTORICO / ANIO_FIN_HISTORICO se importan desde
        scripts/config.py (fuente única) en vez de redefinirse aquí.
        """
        from config import ANIO_INICIO_HISTORICO, ANIO_FIN_HISTORICO
        from detectar_cambios import agrupar_por_anio

        def anios_completos(anios):
            return [{"anio": a, "meses": list(range(1, 13))} for a in sorted(set(anios))]

        conf = get_current_context()["dag_run"].conf or {}
        origen = conf.get("origen", "manual")
        if "periodos" in conf:
            lotes = agrupar_por_anio(conf["periodos"])
            if not all(2000 <= l["anio"] <= 2100 and set(l["meses"]) <= set(range(1, 13)) for l in lotes):
                raise ValueError(f"dag_run.conf['periodos'] fuera de rango: {conf['periodos']}")
            logger.info("Meses recibidos por conf (origen=%s): %s", origen, lotes or "ninguno (solo formularios)")
            return lotes
        if conf.get("anios"):
            anios = [int(a) for a in conf["anios"]]
            if not all(2000 <= a <= 2100 for a in anios):
                raise ValueError(f"dag_run.conf['anios'] fuera de rango: {anios}")
            logger.info("Años recibidos por conf (origen=%s): %s", origen, sorted(set(anios)))
            return anios_completos(anios)

        valor = Variable.get("sietel_anios_a_cargar", default="mensual")

        if valor.strip().lower() == "historico":
            anios = list(range(ANIO_INICIO_HISTORICO, ANIO_FIN_HISTORICO + 1))
            logger.info("Modo histórico: cargando años %s", anios)
            return anios_completos(anios)

        # Intentar interpretar como año(s) numérico(s): "2025" o "2023,2024,2025"
        try:
            partes = [p.strip() for p in valor.split(",") if p.strip()]
            anios = [int(p) for p in partes]
            if all(2000 <= a <= 2100 for a in anios):
                logger.info("Modo año(s) específico(s): cargando %s", anios)
                return anios_completos(anios)
        except ValueError:
            pass

        # Fallback: año en curso
        anio_actual = datetime.now().year
        logger.info("Modo mensual: cargando solo año %s", anio_actual)
        return anios_completos([anio_actual])

    @task
    def cargar_hechos_de_anio(lote: dict):
        from cargar_hechos_anio import cargar_hechos_anio
        cargar_hechos_anio(lote["anio"], lote["meses"])

    # trigger_rule none_failed: si solo cambiaron formularios, no hay lotes
    # de hechos -- la tarea mapeada sobre una lista vacía queda "skipped" y,
    # con la regla por defecto, arrastraría a validación, huella y mart. Si
    # alguna carga FALLA, validar_carga sigue sin correr.
    @task(trigger_rule="none_failed")
    def validar_carga(lotes: list[dict]):
        from validar_carga import validar_anios
        validar_anios([l["anio"] for l in lotes], {l["anio"]: l["meses"] for l in lotes})

    @task
    def guardar_huella_fuente(huella: list[dict], lotes: list[dict]):
        """Solo corre si validar_carga pasó: la huella marca esos meses (y los
        formularios, recargados completos) como cargados y certificados."""
        from detectar_cambios import guardar_huella
        guardar_huella(huella, lotes)

    # 7. disparar_mart_pipeline (28-sep-2026) -- aplicar_esquema hace
    # DROP VIEW analitico.v_ultimo_periodo_reportado_detalle CASCADE, que se
    # lleva mart.vw_prestadores_sin_reportar y mart.vw_nodos_isp_mapa: sin
    # este paso el dashboard (KPI "sin reportar" y Mapa de nodos) quedaba
    # roto hasta que alguien disparara sietel_mart_pipeline a mano (opción
    # b de sql/01_ddl_postgres.sql, sección 6). Solo se dispara si la
    # validación cruzada pasó (trigger_rule por defecto, all_success) -- no
    # se publica en el dashboard un dato que no quedó certificado. No espera
    # a que mart termine: son dos DAGs independientes, con sus propios logs.
    # REQUIERE que sietel_mart_pipeline esté DESPAUSADO en la UI (schedule
    # =None, así que despausarlo no agenda nada por sí solo); si está
    # pausado, la corrida queda en cola sin ejecutarse.
    disparar_mart = TriggerDagRunOperator(
        task_id="disparar_mart_pipeline",
        trigger_dag_id="sietel_mart_pipeline",
        wait_for_completion=False,
    )

    huella = tomar_huella_fuente()
    esquema = aplicar_esquema()
    dimensiones = cargar_dimensiones()
    nodos = cargar_nodos_isp()
    formularios = cargar_formularios_lineas()
    lotes = obtener_periodos_a_cargar()
    hechos = cargar_hechos_de_anio.expand(lote=lotes)
    validacion = validar_carga(lotes)
    huella_guardada = guardar_huella_fuente(huella, lotes)

    huella >> esquema >> dimensiones >> nodos >> formularios >> hechos >> validacion >> huella_guardada >> disparar_mart


sietel_usuarios_cuentas_pipeline()
