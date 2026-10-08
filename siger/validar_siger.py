"""
siger/validar_siger.py — Validación cruzada SIGER_V3 vs. esquema siger,
DESPUÉS del COMMIT de las cargas (estilo de scripts/validar_carga.py:
reporte ✅/❌ y ValidacionFallida para que la tarea quede en rojo).

Por cada tabla, vuelve a leer el origen completo y lo compara contra lo ya
confirmado en PostgreSQL:
  1. conteo origen = destino;
  2. hash MD5 fila a fila en AMBAS direcciones: faltantes en destino Y
     sobrantes en destino (la mitad que validar_carga.py no veía antes del
     incidente del 25-sep-2026). Sin llave natural confiable en facturación,
     se compara el multiconjunto de hashes;
  3. hash_contenido guardado = hash recalculado desde los valores guardados
     (detecta ediciones por fuera del pipeline).
Además:
  4. Acceso (LOPDP): ningún rol del dashboard con USAGE en siger; mart_user
     sin SELECT sobre siger.concesionario pero con SELECT sobre
     siger.v_concesionario_basico.
  5. Unicidad de ucp_concnum en siger.concesionario (aviso, no fallo: la
     vista de origen no la garantiza).
  6. Métricas de referencia de la instrucción (§9), impresas como
     REFERENCIA, no como asserts.

La carga ya certificó lo mismo ANTES del COMMIT contra lo que extrajo; esta
validación además detecta cambios en SIGER entre la carga y ahora, y
cualquier alteración posterior del destino. Si SIGER cambió en ese lapso
(es una base viva), puede fallar sin que la carga esté mal: relanzar el DAG.

Desde el 08-oct-2026 el DAG solo la corre si alguna tabla se recargó, y solo
sobre esas tablas (las demás no cambiaron: misma huella). Si una tabla no
certifica, se borra su huella (siger.huella_fuente) para que la próxima
corrida la recargue aunque SIGER no cambie.
"""
import logging
from datetime import datetime

from cargar_siger import TABLAS, iterar_origen, restar_destino, resumir_balance
from config_siger import postgres_conexion, postgres_cursor
from huella_siger import invalidar_huellas

logger = logging.getLogger(__name__)

ROLES_SIN_ACCESO_A_SIGER = ("dashboard_lector", "dashboard_auth", "calidad_lector",
                            "calidad_revisor", "eda_lector")


class ValidacionFallida(Exception):
    pass


def _certificar_tabla(clave: str) -> dict:
    tabla = TABLAS[clave]
    t0 = datetime.now()
    balance: dict[bytes, int] = {}
    n_origen = 0
    for _valores, _derivadas, d in iterar_origen(tabla, derivar=False):
        balance[d] = balance.get(d, 0) + 1
        n_origen += 1
    conn = postgres_conexion()
    try:
        n_destino, inconsistentes = restar_destino(conn, tabla, balance)
    finally:
        conn.rollback()
        conn.close()
    faltantes, sobrantes = resumir_balance(balance)
    return {
        "tabla": tabla.destino,
        "origen": n_origen,
        "destino": n_destino,
        "faltantes": faltantes,
        "sobrantes": sobrantes,
        "inconsistentes": inconsistentes,
        "segundos": (datetime.now() - t0).total_seconds(),
    }


def _verificar_accesos(cur) -> list[str]:
    problemas = []
    for rol in ROLES_SIN_ACCESO_A_SIGER:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AS existe", (rol,))
        if not cur.fetchone()["existe"]:
            continue
        cur.execute("SELECT has_schema_privilege(%s, 'siger', 'USAGE') AS v", (rol,))
        if cur.fetchone()["v"]:
            problemas.append(f"El rol {rol} tiene USAGE en el esquema siger (ningún rol del dashboard debe tenerlo)")
    cur.execute("SELECT has_table_privilege('mart_user', 'siger.concesionario', 'SELECT') AS v")
    if cur.fetchone()["v"]:
        problemas.append("mart_user tiene SELECT sobre siger.concesionario (datos personales, LOPDP)")
    cur.execute("SELECT has_table_privilege('mart_user', 'siger.v_concesionario_basico', 'SELECT') AS v")
    if not cur.fetchone()["v"]:
        problemas.append("mart_user NO tiene SELECT sobre siger.v_concesionario_basico (lo necesita el cruce con OBTEL)")
    return problemas


# Métricas de referencia (§9 de la instrucción, valores observados el
# 05-oct-2026). Se imprimen para comparar a ojo; NO hacen fallar la tarea.
SQL_METRICAS = [
    ("Títulos (todos los servicios y estados)", "34.266", "SELECT COUNT(*) AS v FROM siger.titulo_habilitante"),
    ("Servicios", "40", "SELECT COUNT(*) AS v FROM siger.servicio_th"),
    ("Concesionarios", "27.280", "SELECT COUNT(*) AS v FROM siger.concesionario"),
    ("Títulos SAI vigentes por IDSTH", "9=2.462, 33=5, 31=1",
     "SELECT string_agg(idsth || '=' || n, ', ' ORDER BY idsth) AS v FROM "
     "(SELECT idsth, COUNT(*) AS n FROM siger.v_titulo_sai WHERE es_vigente GROUP BY idsth) x"),
    ("RUC distintos con SAI vigente IDSTH 9", "1.379",
     "SELECT COUNT(DISTINCT c.ruc_resuelto) AS v FROM siger.v_titulo_sai t "
     "JOIN siger.concesionario c ON btrim(c.ucp_concnum) = t.ucp_concnum WHERE t.es_vigente AND t.idsth = 9"),
    ("Títulos SAI vigentes IDSTH 9 sin RUC resuelto", "0",
     "SELECT COUNT(*) AS v FROM siger.v_titulo_sai t "
     "LEFT JOIN siger.concesionario c ON btrim(c.ucp_concnum) = t.ucp_concnum "
     "WHERE t.es_vigente AND t.idsth = 9 AND c.ruc_resuelto IS NULL"),
    ("Títulos SAI vigentes IDSTH 9 resueltos por cedula_001", "448",
     "SELECT COUNT(*) AS v FROM siger.v_titulo_sai t "
     "JOIN siger.concesionario c ON btrim(c.ucp_concnum) = t.ucp_concnum "
     "WHERE t.es_vigente AND t.idsth = 9 AND c.ruc_origen = 'cedula_001'"),
    ("Filas de facturación", "≈2,48 M", "SELECT COUNT(*) AS v FROM siger.facturacion_espectro"),
    ("Contratos distintos en facturación", "2.817",
     "SELECT COUNT(DISTINCT upper(contrato_key)) AS v FROM siger.facturacion_espectro"),
    ("Contratos enlazados por tomo-foja", "2.729",
     "SELECT COUNT(DISTINCT upper(contrato_key)) AS v FROM siger.facturacion_espectro "
     "WHERE tipo_enlace = 'TOMO_FOJA'"),
    ("Filas de facturación por tipo_enlace", "-",
     "SELECT string_agg(tipo_enlace || '=' || n, ', ' ORDER BY tipo_enlace) AS v FROM "
     "(SELECT tipo_enlace, COUNT(*) AS n FROM siger.facturacion_espectro GROUP BY tipo_enlace) x"),
    ("Prestadores SAI con anomalías (vigencias distintas / solo sin tomo-foja / varios con tomo-foja)",
     "~29 / ~10 / ~2",
     "SELECT COUNT(*) FILTER (WHERE anom_vigencias_distintas) || ' / ' || "
     "COUNT(*) FILTER (WHERE anom_solo_sin_tomo_foja) || ' / ' || "
     "COUNT(*) FILTER (WHERE anom_varios_con_tomo_foja) AS v FROM siger.v_prestador_sai"),
]


def _registrar_resultado(estado, mensaje_error, fecha_inicio):
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES ('siger_validacion', NULL, NULL, NULL, %s, %s, %s)
            """,
            (estado, mensaje_error, fecha_inicio),
        )


def validar_siger(claves: list[str] | None = None):
    """Certifica las tablas indicadas (todas si claves=None) y los accesos."""
    inicio = datetime.now()
    errores = []
    resultados = []
    sin_certificar = []

    for clave in (claves if claves is not None else TABLAS):
        print(f"Certificando {TABLAS[clave].destino} contra {TABLAS[clave].objeto}...")
        r = _certificar_tabla(clave)
        resultados.append(r)
        if (r["origen"] != r["destino"] or r["faltantes"] or r["sobrantes"]
                or r["inconsistentes"]):
            sin_certificar.append(TABLAS[clave].tipo_carga)
        if r["origen"] != r["destino"]:
            errores.append(f"{r['tabla']}: {r['origen']:,} filas en SIGER vs {r['destino']:,} en PostgreSQL")
        if r["faltantes"]:
            errores.append(f"{r['tabla']}: {r['faltantes']} fila(s) de SIGER que faltan en PostgreSQL")
        if r["sobrantes"]:
            errores.append(f"{r['tabla']}: {r['sobrantes']} fila(s) en PostgreSQL que SIGER ya no tiene")
        if r["inconsistentes"]:
            errores.append(f"{r['tabla']}: {r['inconsistentes']} fila(s) con hash_contenido distinto de sus "
                           f"valores (posible edición por fuera del pipeline)")

    with postgres_cursor(commit=False) as cur:
        problemas_acceso = _verificar_accesos(cur)
        errores.extend(problemas_acceso)
        cur.execute("SELECT COUNT(*) - COUNT(DISTINCT btrim(ucp_concnum)) AS v FROM siger.concesionario")
        duplicados_concnum = cur.fetchone()["v"]
        metricas = []
        for nombre, referencia, sql in SQL_METRICAS:
            cur.execute(sql)
            metricas.append((nombre, referencia, cur.fetchone()["v"]))

    print(f"\n{'=' * 78}\n📊 REPORTE DE VALIDACIÓN — SIGER_V3 → siger\n{'=' * 78}")
    for r in resultados:
        ok = (r["origen"] == r["destino"] and not r["faltantes"] and not r["sobrantes"]
              and not r["inconsistentes"])
        print(f"  {r['tabla']:<30} {r['origen']:>10,} SIGER / {r['destino']:>10,} PG  "
              f"faltan {r['faltantes']}, sobran {r['sobrantes']}, hash incons. {r['inconsistentes']}  "
              f"({r['segundos']:.0f}s)  {'✅' if ok else '❌'}")
    print(f"  Accesos (LOPDP, roles del dashboard)                     {'❌' if problemas_acceso else '✅'}")
    for p in problemas_acceso:
        print(f"    ⚠️  {p}")
    print(f"  ucp_concnum únicos en siger.concesionario                "
          f"{'✅' if not duplicados_concnum else f'⚠️  {duplicados_concnum} repetidos (aviso)'}")
    print(f"  {'─' * 74}\n  Métricas (referencia del 05-oct-2026, no son asserts):")
    for nombre, referencia, valor in metricas:
        print(f"    {nombre}: {valor}   [ref. {referencia}]")
    print(f"{'=' * 78}")

    if sin_certificar:
        with postgres_cursor() as cur:
            invalidar_huellas(cur, sin_certificar)
        print(f"  Huella borrada de {', '.join(sin_certificar)}: se recargarán en la próxima corrida.")

    if errores:
        mensaje = "; ".join(errores)
        print("❌ ESTADO: la validación encontró discrepancias -- ver detalle arriba\n")
        _registrar_resultado("FALLIDO", mensaje, inicio)
        raise ValidacionFallida(f"Validación SIGER encontró {len(errores)} problema(s): {mensaje}")

    print("✅ ESTADO: réplica de SIGER certificada en ambas direcciones\n")
    _registrar_resultado("EXITOSO", None, inicio)
    logger.info("Validación SIGER exitosa.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    validar_siger()
