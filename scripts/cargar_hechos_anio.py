"""
Extracción y carga de hechos agregados de dbo.VALineasDedicadas hacia
staging.va_lineas_dedicadas_resumen.

Agregación GROUP BY ejecutada en SQL Server (no se transfiere detalle
crudo). Rangos clasificados por downLink/upLink en Kbps:
  lineas_dl/ul_sin_datos, menos_1mbps, 1_10mbps, 10_30mbps,
  30_100mbps, 100mbps_1gbps, 1gbps_o_mas.

Cardinalidad verificada enero 2025: tipoEnlace(4), tipoCliente(3),
nivelComparticion(14), portador(138).
upLink(1.457) y downLink(955) → NO en GROUP BY, se convierten en métricas.

CAMBIO (20-jul-2026): lineas_dl/ul_* reemplaza a usuarios_dl/ul_*.
-------------------------------------------------------------------
Las columnas por rango de velocidad medían SUM(numeroUsuarios) -- total de
usuarios finales en ese rango. El área de Mercados necesita CONTEO DE
LÍNEAS/CUENTAS en ese rango, no usuarios finales (dos magnitudes distintas:
una línea compartida puede reportar varios usuarios). Se reemplazaron
-- no se agregaron -- las columnas: mismo nombre de rango, prefijo
lineas_ en vez de usuarios_, y la fórmula pasa de SUM(numeroUsuarios) a
un conteo de filas (SUM(CASE WHEN cond THEN 1 ELSE 0 END)).
total_lineas y total_usuarios (los totales generales, no por rango) NO
cambian -- siguen siendo COUNT(*) y SUM(numeroUsuarios) respectivamente,
tal como se confirmó explícitamente con Iván antes de este cambio.

No se agrega fechaCreacion en este cambio (decisión explícita: evitar
tener que reconstruir el índice IX_VALineasDedicadas_Analitico de nuevo).

IMPORTANTE: validar_carga.py importa SQL_EXTRAER_HECHOS_ANIO, COLUMNAS_HASH
y calcular_hash_fila desde este módulo -- no necesita cambios propios
porque no referencia nombres de columna de rango directamente, solo
itera sobre COLUMNAS_HASH genéricamente.

AVISO PARA QUIEN CORRA ESTE CAMBIO: como esto no es un simple rename sino
un cambio de fórmula, cualquier año ya cargado (ej. 2025 en la copia)
tiene que volver a cargarse -- el UPSERT es idempotente por llave natural,
así que volver a correr cargar_hechos_anio(anio) es seguro y sobrescribe
los valores viejos (que quedarían con el nombre nuevo pero el dato viejo
de SUM(numeroUsuarios) si no se recarga).
"""
import argparse
import hashlib
import logging
from datetime import datetime

from psycopg2.extras import execute_batch

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

COLUMNAS_HASH = [
    "peva_codigo", "par_codigo", "periodoNumero", "anio",
    "tipoEnlace", "tipoCliente", "nivelComparticion", "portador",
    "total_lineas", "total_usuarios",
    # Rangos downLink (conteo de líneas, no de usuarios)
    "lineas_dl_sin_datos",
    "lineas_dl_menos_1mbps",
    "lineas_dl_1_10mbps",
    "lineas_dl_10_30mbps",
    "lineas_dl_30_100mbps",
    "lineas_dl_100mbps_1gbps",
    "lineas_dl_1gbps_o_mas",
    # Rangos upLink (conteo de líneas, no de usuarios)
    "lineas_ul_sin_datos",
    "lineas_ul_menos_1mbps",
    "lineas_ul_1_10mbps",
    "lineas_ul_10_30mbps",
    "lineas_ul_30_100mbps",
    "lineas_ul_100mbps_1gbps",
    "lineas_ul_1gbps_o_mas",
]

MESES_DEL_ANIO = list(range(1, 13))

NOMBRE_MES = [
    None, "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def calcular_hash_fila(fila: dict) -> str:
    valores = [
        str(fila.get(col)) if fila.get(col) is not None else "NULL"
        for col in COLUMNAS_HASH
    ]
    return hashlib.md5("|".join(valores).encode("utf-8")).hexdigest()


SQL_EXTRAER_HECHOS_ANIO = """
    SELECT
        ld.peva_codigo,
        ld.par_codigo,
        ld.periodoNumero,
        ld.periodoNombre,
        ld.anio,
        ld.tipoEnlace,
        ld.tipoCliente,
        ld.nivelComparticion,
        ld.portador,
        ld.regional,
        prov.pro_nombre,
        ciu.ciu_nombre,
        par.par_nombre,
        -- Volumen total (sin cambios: total_lineas = COUNT(*),
        -- total_usuarios = SUM(numeroUsuarios))
        COUNT(*)                                                    AS total_lineas,
        SUM(ld.numeroUsuarios)                                      AS total_usuarios,

        -- ── Clasificación por downLink (velocidad de bajada) ──────────────
        -- CONTEO DE LÍNEAS en cada rango, no SUM(numeroUsuarios).
        -- Sin datos: NULL o 0 Kbps — no reportado por el prestador
        SUM(CASE WHEN ld.downLink IS NULL OR ld.downLink = 0
                 THEN 1 ELSE 0 END)                                 AS lineas_dl_sin_datos,
        -- < 1 Mbps: sin banda ancha básica, brecha digital
        SUM(CASE WHEN ld.downLink > 0 AND ld.downLink < 1024
                 THEN 1 ELSE 0 END)                                 AS lineas_dl_menos_1mbps,
        -- 1 – 10 Mbps: banda ancha básica (umbral mínimo ITU)
        SUM(CASE WHEN ld.downLink >= 1024 AND ld.downLink < 10240
                 THEN 1 ELSE 0 END)                                 AS lineas_dl_1_10mbps,
        -- 10 – 30 Mbps: banda ancha media (umbral básico OCDE)
        SUM(CASE WHEN ld.downLink >= 10240 AND ld.downLink < 30720
                 THEN 1 ELSE 0 END)                                 AS lineas_dl_10_30mbps,
        -- 30 – 100 Mbps: banda ancha avanzada (umbral UE)
        SUM(CASE WHEN ld.downLink >= 30720 AND ld.downLink < 102400
                 THEN 1 ELSE 0 END)                                 AS lineas_dl_30_100mbps,
        -- 100 Mbps – 1 Gbps: ultra banda ancha (segmento dominante en Ecuador)
        SUM(CASE WHEN ld.downLink >= 102400 AND ld.downLink < 1048576
                 THEN 1 ELSE 0 END)                                 AS lineas_dl_100mbps_1gbps,
        -- ≥ 1 Gbps: gigabit (segmento premium)
        SUM(CASE WHEN ld.downLink >= 1048576
                 THEN 1 ELSE 0 END)                                 AS lineas_dl_1gbps_o_mas,

        -- ── Clasificación por upLink (velocidad de subida) ────────────────
        -- CONTEO DE LÍNEAS en cada rango, no SUM(numeroUsuarios).
        SUM(CASE WHEN ld.upLink IS NULL OR ld.upLink = 0
                 THEN 1 ELSE 0 END)                                 AS lineas_ul_sin_datos,
        SUM(CASE WHEN ld.upLink > 0 AND ld.upLink < 1024
                 THEN 1 ELSE 0 END)                                 AS lineas_ul_menos_1mbps,
        SUM(CASE WHEN ld.upLink >= 1024 AND ld.upLink < 10240
                 THEN 1 ELSE 0 END)                                 AS lineas_ul_1_10mbps,
        SUM(CASE WHEN ld.upLink >= 10240 AND ld.upLink < 30720
                 THEN 1 ELSE 0 END)                                 AS lineas_ul_10_30mbps,
        SUM(CASE WHEN ld.upLink >= 30720 AND ld.upLink < 102400
                 THEN 1 ELSE 0 END)                                 AS lineas_ul_30_100mbps,
        SUM(CASE WHEN ld.upLink >= 102400 AND ld.upLink < 1048576
                 THEN 1 ELSE 0 END)                                 AS lineas_ul_100mbps_1gbps,
        SUM(CASE WHEN ld.upLink >= 1048576
                 THEN 1 ELSE 0 END)                                 AS lineas_ul_1gbps_o_mas

    FROM dbo.VALineasDedicadas ld
    LEFT JOIN dbo.Parroquia par  ON par.par_codigo  = ld.par_codigo
    LEFT JOIN dbo.Ciudad    ciu  ON ciu.ciu_codigo  = par.ciu_codigo
    LEFT JOIN dbo.Provincia prov ON prov.pro_codigo = ciu.pro_codigo
    WHERE ld.anio = ? AND ld.periodoNumero = ?
    GROUP BY
        ld.peva_codigo, ld.par_codigo, ld.periodoNumero,
        ld.periodoNombre, ld.anio, ld.tipoEnlace,
        ld.tipoCliente, ld.nivelComparticion, ld.portador,
        ld.regional, prov.pro_nombre, ciu.ciu_nombre, par.par_nombre
"""

SQL_UPSERT_HECHOS = """
    INSERT INTO staging.va_lineas_dedicadas_resumen (
        peva_codigo, par_codigo, periodoNumero, periodoNombre, anio,
        tipoEnlace, tipoCliente, nivelComparticion, portador, regional,
        pro_nombre, ciu_nombre, par_nombre,
        total_lineas, total_usuarios,
        lineas_dl_sin_datos, lineas_dl_menos_1mbps,
        lineas_dl_1_10mbps, lineas_dl_10_30mbps,
        lineas_dl_30_100mbps, lineas_dl_100mbps_1gbps,
        lineas_dl_1gbps_o_mas,
        lineas_ul_sin_datos, lineas_ul_menos_1mbps,
        lineas_ul_1_10mbps, lineas_ul_10_30mbps,
        lineas_ul_30_100mbps, lineas_ul_100mbps_1gbps,
        lineas_ul_1gbps_o_mas,
        hash_contenido
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (peva_codigo, par_codigo, periodoNumero, anio,
                 tipoEnlace, tipoCliente, nivelComparticion, portador)
    DO UPDATE SET
        periodoNombre             = EXCLUDED.periodoNombre,
        regional                  = EXCLUDED.regional,
        pro_nombre                = EXCLUDED.pro_nombre,
        ciu_nombre                = EXCLUDED.ciu_nombre,
        par_nombre                = EXCLUDED.par_nombre,
        total_lineas              = EXCLUDED.total_lineas,
        total_usuarios            = EXCLUDED.total_usuarios,
        lineas_dl_sin_datos       = EXCLUDED.lineas_dl_sin_datos,
        lineas_dl_menos_1mbps     = EXCLUDED.lineas_dl_menos_1mbps,
        lineas_dl_1_10mbps        = EXCLUDED.lineas_dl_1_10mbps,
        lineas_dl_10_30mbps       = EXCLUDED.lineas_dl_10_30mbps,
        lineas_dl_30_100mbps      = EXCLUDED.lineas_dl_30_100mbps,
        lineas_dl_100mbps_1gbps   = EXCLUDED.lineas_dl_100mbps_1gbps,
        lineas_dl_1gbps_o_mas     = EXCLUDED.lineas_dl_1gbps_o_mas,
        lineas_ul_sin_datos       = EXCLUDED.lineas_ul_sin_datos,
        lineas_ul_menos_1mbps     = EXCLUDED.lineas_ul_menos_1mbps,
        lineas_ul_1_10mbps        = EXCLUDED.lineas_ul_1_10mbps,
        lineas_ul_10_30mbps       = EXCLUDED.lineas_ul_10_30mbps,
        lineas_ul_30_100mbps      = EXCLUDED.lineas_ul_30_100mbps,
        lineas_ul_100mbps_1gbps   = EXCLUDED.lineas_ul_100mbps_1gbps,
        lineas_ul_1gbps_o_mas     = EXCLUDED.lineas_ul_1gbps_o_mas,
        hash_contenido            = EXCLUDED.hash_contenido,
        fecha_carga               = now()
"""


def _fila_a_tupla(fila: dict, hash_fila: str) -> tuple:
    """
    Convierte una fila (dict, vía _DictCursorWrapper) a la tupla posicional
    que espera SQL_UPSERT_HECHOS, en el orden EXACTO de columnas del INSERT.
    Si se agrega una columna al DDL o al SELECT, hay que agregarla aquí
    también, en la misma posición.
    """
    return (
        fila["peva_codigo"], fila["par_codigo"],
        fila["periodoNumero"], fila["periodoNombre"],
        fila["anio"], fila["tipoEnlace"],
        fila["tipoCliente"], fila["nivelComparticion"],
        fila["portador"], fila["regional"],
        fila["pro_nombre"], fila["ciu_nombre"], fila["par_nombre"],
        fila["total_lineas"], fila["total_usuarios"],
        fila["lineas_dl_sin_datos"],
        fila["lineas_dl_menos_1mbps"],
        fila["lineas_dl_1_10mbps"],
        fila["lineas_dl_10_30mbps"],
        fila["lineas_dl_30_100mbps"],
        fila["lineas_dl_100mbps_1gbps"],
        fila["lineas_dl_1gbps_o_mas"],
        fila["lineas_ul_sin_datos"],
        fila["lineas_ul_menos_1mbps"],
        fila["lineas_ul_1_10mbps"],
        fila["lineas_ul_10_30mbps"],
        fila["lineas_ul_30_100mbps"],
        fila["lineas_ul_100mbps_1gbps"],
        fila["lineas_ul_1gbps_o_mas"],
        hash_fila,
    )


def _cargar_mes(ms_cur, pg_cur, anio: int, mes: int) -> int:
    """
    Extrae y carga un único mes (anio, periodoNumero=mes).
    Usa execute_batch en vez de un execute() por fila: reemplaza N
    round-trips de red a Postgres por N/page_size round-trips, mismo
    patrón que samm_pipeline/app/utils/postgres_handler.py.

    Mide por separado el tiempo de extracción (SQL Server) y el tiempo
    de upsert (Postgres) -- no asumir cuál de los dos domina el tiempo
    total sin medirlo por separado.
    """
    nombre_mes = NOMBRE_MES[mes]
    print(f"  Mes {mes:>2}/12 ({nombre_mes:<10}) — extrayendo de SQL Server...")

    t_extraccion_inicio = datetime.now()
    ms_cur.execute(SQL_EXTRAER_HECHOS_ANIO, (anio, mes))
    filas = ms_cur.fetchall()
    t_extraccion = (datetime.now() - t_extraccion_inicio).total_seconds()

    if not filas:
        print(f"  Mes {mes:>2}/12 ({nombre_mes:<10}) — 0 filas (sin datos reportados)")
        logger.info("Año %s, mes %s: 0 filas agregadas (sin datos reportados).", anio, mes)
        return 0

    t_upsert_inicio = datetime.now()
    tuplas = [_fila_a_tupla(fila, calcular_hash_fila(fila)) for fila in filas]
    execute_batch(pg_cur, SQL_UPSERT_HECHOS, tuplas, page_size=1000)
    t_upsert = (datetime.now() - t_upsert_inicio).total_seconds()

    print(
        f"  Mes {mes:>2}/12 ({nombre_mes:<10}) — {len(tuplas):,} filas → upsert OK  "
        f"[SQL Server: {t_extraccion:.2f}s | Postgres upsert: {t_upsert:.2f}s]"
    )
    logger.info(
        "Año %s, mes %s: %s filas agregadas procesadas (extraccion=%.2fs, upsert=%.2fs).",
        anio, mes, len(tuplas), t_extraccion, t_upsert,
    )
    return len(tuplas)


def cargar_hechos_anio(anio: int):
    """
    Carga el año completo iterando mes a mes (periodoNumero 1..12).

    Por qué mes a mes y no el año de una sola vez:
      1. Aprovecha el prefijo (anio, periodoNumero) del índice
         IX_VALineasDedicadas_Analitico -> cada consulta mensual usa el
         índice de forma óptima en vez de escanear el año completo.
      2. Acota el radio de un fallo a un mes, no al año entero -- si un
         mes específico tiene un dato corrupto, el resto del año no se
         pierde ni hay que reprocesarlo (el UPSERT es idempotente por mes).
      3. Reduce el volumen mantenido en memoria por consulta.

    Una sola conexión Postgres para todo el año (un commit al final,
    vía postgres_cursor()), pero con execute_batch por mes en vez de
    execute() fila por fila -- las dos causas originales del problema
    de rendimiento se atacan juntas, no por separado.
    """
    inicio = datetime.now()
    filas_procesadas = 0
    print(f"\n{'=' * 60}")
    print(f"CARGA DE HECHOS — AÑO {anio} (particionado por mes)")
    print(f"{'=' * 60}")
    try:
        with sqlserver_cursor() as ms_cur, postgres_cursor() as pg_cur:
            for mes in MESES_DEL_ANIO:
                filas_procesadas += _cargar_mes(ms_cur, pg_cur, anio, mes)

        duracion = (datetime.now() - inicio).total_seconds()
        print(f"{'-' * 60}")
        print(f"✅ Año {anio} completo: {filas_procesadas:,} filas agregadas en {duracion:.1f}s")
        print(f"{'=' * 60}\n")
        _registrar_carga("hechos_anual", anio, filas_procesadas, 0, "EXITOSO", None, inicio)
        logger.info("Año %s: %s filas agregadas procesadas (12 meses).", anio, filas_procesadas)

    except Exception as exc:
        print(f"❌ Año {anio} FALLÓ tras {filas_procesadas:,} filas procesadas: {exc}")
        _registrar_carga("hechos_anual", anio, filas_procesadas, 0, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando hechos del año %s", anio)
        raise


def _registrar_carga(tipo_carga, anio, insertadas, actualizadas, estado, mensaje_error, fecha_inicio):
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (tipo_carga, anio, insertadas, actualizadas, estado, mensaje_error, fecha_inicio),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Carga agregado anual (particionado por mes) de "
                    "dbo.VALineasDedicadas hacia staging.va_lineas_dedicadas_resumen."
    )
    parser.add_argument("--anio", type=int, required=True, help="Año a cargar, ej. 2025")
    parser.add_argument(
        "--mes", type=int, default=None,
        help="Mes específico 1-12 para una prueba puntual (ej. smoke test antes del histórico). "
             "Si se omite, carga los 12 meses del año.",
    )
    args = parser.parse_args()

    if args.mes is not None:
        t0 = datetime.now()
        with sqlserver_cursor() as ms_cur, postgres_cursor() as pg_cur:
            n = _cargar_mes(ms_cur, pg_cur, args.anio, args.mes)
        duracion = (datetime.now() - t0).total_seconds()
        tasa = n / duracion if duracion > 0 else 0
        print(
            f"Año {args.anio}, mes {args.mes}: {n:,} filas agregadas procesadas "
            f"en {duracion:.2f}s ({tasa:,.0f} filas/s)."
        )
    else:
        cargar_hechos_anio(args.anio)
