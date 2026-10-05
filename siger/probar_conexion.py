"""
siger/probar_conexion.py — Prueba de conectividad SIGER_V3 (primer entregable,
antes de cualquier carga). Solo LEE; no escribe nada en ningún lado.

Desde el contenedor de Airflow (VM2):
    docker compose exec airflow-scheduler python /opt/airflow/siger/probar_conexion.py
    docker compose exec airflow-scheduler python /opt/airflow/siger/probar_conexion.py --pg

Pasos:
  a. Conecta a SIGER_V3 con el driver ODBC 18 (mismas opciones TLS que SIETEL).
  b. Imprime @@VERSION, login, usuario de base y base actual.
  c. Verifica los permisos de las columnas permitidas (§2) -- fn_my_permissions
     por columna + SELECT TOP 0 de las columnas exactas.
  d. Cuenta las filas de cada objeto (sin SELECT * ni COUNT(*) sobre columnas
     denegadas) y vuelca INFORMATION_SCHEMA.COLUMNS de los 4 objetos -- con
     ese volcado se cierran los tipos del DDL de la fase 2.
  e. Comprueba que THSECUENCIAL (float) sea siempre entero y único.
  --pg: además, comprobaciones de solo lectura en PostgreSQL como siger_user
        (esquema siger, dueño, grants y default privileges hacia mart_user).

RIESGO CONOCIDO: SQL Server 2012 SP2 (build 11.0.5058) puede no soportar
TLS 1.2. Si el handshake falla se imprime el error exacto de pyodbc y el
ajuste mínimo sugerido del openssl.cnf del Dockerfile -- NO se aplica.
"""
import argparse
import logging
import sys

from config_siger import (
    COLUMNA_CONTEO,
    COLUMNAS_PERMITIDAS,
    PermisoDenegado,
    columnas_de_origen,
    postgres_cursor,
    sqlserver_cursor,
    verificar_permisos,
)

logger = logging.getLogger(__name__)

SUGERENCIA_TLS = """
  El handshake TLS falló. SQL Server 2012 SP2 (11.0.5058) sin el parche de
  TLS 1.2 solo negocia TLS 1.0/1.1, que OpenSSL 3 rechaza por defecto.
  Ajuste mínimo sugerido (NO aplicado) en docker/Dockerfile, dentro del
  bloque que ya genera /etc/ssl/openssl-legacy-renegotiation.cnf, sección
  [system_default_sect]:

      echo "Options = UnsafeLegacyRenegotiation"; \\
      echo "MinProtocol = TLSv1"; \\
      echo "CipherString = DEFAULT@SECLEVEL=0"; \\

  Afecta a TODO el contenedor (también a la conexión con SIETEL): baja el
  piso de seguridad TLS. La solución de fondo es del lado de SIGER
  (actualizar SQL Server 2012 a un build con TLS 1.2). Si el error NO
  menciona SSL/TLS, el problema es otro (red, firewall, credenciales).
"""

PALABRAS_TLS = ("ssl", "tls", "handshake", "protocol", "encryption", "cipher")

ROLES_SIN_ACCESO_A_SIGER = ("dashboard_lector", "dashboard_auth", "calidad_lector",
                            "calidad_revisor", "eda_lector")


def _titulo(texto: str) -> None:
    print(f"\n{'=' * 70}\n{texto}\n{'=' * 70}")


def _probar_sqlserver() -> bool:
    ok = True
    _titulo("a/b. Conexión a SIGER_V3 (ODBC 18)")
    try:
        cm = sqlserver_cursor()
        cur = cm.__enter__()
    except Exception as exc:
        print(f"  ❌ No se pudo conectar: {exc!r}")
        if any(p in str(exc).lower() for p in PALABRAS_TLS):
            print(SUGERENCIA_TLS)
        return False

    try:
        cur.execute("SELECT @@VERSION AS version, SUSER_SNAME() AS login, "
                    "USER_NAME() AS usuario, DB_NAME() AS base")
        r = cur.fetchone()
        print(f"  ✅ Conectado\n  Login: {r['login']}  |  Usuario: {r['usuario']}  |  Base: {r['base']}")
        print("  " + r["version"].replace("\n", "\n  "))
        try:
            cur.execute("SELECT encrypt_option, protocol_version FROM sys.dm_exec_connections "
                        "WHERE session_id = @@SPID")
            c = cur.fetchone()
            print(f"  Cifrado: {c['encrypt_option']}  |  Protocolo TDS: {c['protocol_version']}")
        except Exception as exc:  # requiere VIEW SERVER STATE; informativo
            print(f"  (sin acceso a sys.dm_exec_connections: {exc.__class__.__name__})")

        for objeto, columnas in COLUMNAS_PERMITIDAS.items():
            _titulo(f"c/d. {objeto}")
            meta = columnas_de_origen(cur, objeto)
            if not meta:
                print("  ❌ INFORMATION_SCHEMA.COLUMNS no devuelve columnas (¿objeto inexistente o sin permisos?)")
                ok = False
                continue
            columnas = columnas or [m["COLUMN_NAME"] for m in meta]
            visibles = {m["COLUMN_NAME"].lower() for m in meta}
            faltan = [c for c in columnas if c.lower() not in visibles]
            if faltan:
                print(f"  ❌ Columnas esperadas que no existen/no son visibles: {faltan}")
                ok = False
            try:
                verificar_permisos(cur, objeto, columnas)
                print(f"  ✅ Permiso SELECT en las {len(columnas)} columnas a usar")
            except PermisoDenegado as exc:
                print(f"  ❌ {exc}")
                ok = False

            col_conteo = COLUMNA_CONTEO[objeto] or columnas[0]
            try:
                cur.execute(f"SELECT COUNT_BIG(*) AS n FROM (SELECT [{col_conteo}] FROM {objeto}) t")
                print(f"  Filas: {cur.fetchone()['n']:,}")
            except Exception as exc:
                print(f"  ❌ Conteo falló: {exc}")
                ok = False

            print(f"  Columnas visibles en INFORMATION_SCHEMA ({len(meta)}):")
            print(f"    {'#':>3}  {'columna':<32} {'tipo':<16} {'long':>6} {'prec':>5} {'esc':>4} {'dtp':>4} nulo")
            for m in meta:
                print(f"    {m['ORDINAL_POSITION']:>3}  {m['COLUMN_NAME']:<32} {m['DATA_TYPE']:<16} "
                      f"{str(m['CHARACTER_MAXIMUM_LENGTH'] or ''):>6} {str(m['NUMERIC_PRECISION'] or ''):>5} "
                      f"{str(m['NUMERIC_SCALE'] if m['NUMERIC_SCALE'] is not None else ''):>4} "
                      f"{str(m['DATETIME_PRECISION'] if m['DATETIME_PRECISION'] is not None else ''):>4} "
                      f"{m['IS_NULLABLE']}")

        _titulo("e. Integridad de llaves")
        try:
            cur.execute(
                "SELECT COUNT_BIG(*) AS total, COUNT_BIG(DISTINCT THSECUENCIAL) AS distintos, "
                "SUM(CASE WHEN THSECUENCIAL IS NULL THEN 1 ELSE 0 END) AS nulos, "
                "SUM(CASE WHEN THSECUENCIAL <> FLOOR(THSECUENCIAL) THEN 1 ELSE 0 END) AS no_enteros "
                "FROM dbo.TITULO_HABILITANTE"
            )
            r = cur.fetchone()
            ok_th = r["total"] == r["distintos"] and not r["nulos"] and not r["no_enteros"]
            print(f"  THSECUENCIAL: {r['total']:,} filas, {r['distintos']:,} distintos, "
                  f"{r['nulos'] or 0} NULL, {r['no_enteros'] or 0} no enteros  {'✅' if ok_th else '❌'}")
            ok = ok and ok_th
            cur.execute("SELECT COUNT_BIG(*) AS total, COUNT_BIG(DISTINCT ucp_concnum) AS distintos "
                        "FROM dbo.VISTA_CONCESIONARIOS")
            r = cur.fetchone()
            print(f"  VISTA_CONCESIONARIOS.ucp_concnum: {r['total']:,} filas, {r['distintos']:,} distintos  "
                  f"{'✅' if r['total'] == r['distintos'] else '⚠️'}")
            cur.execute("SELECT COUNT_BIG(*) AS total, COUNT_BIG(DISTINCT IDSTH) AS distintos FROM dbo.SERVICIO_TH")
            r = cur.fetchone()
            print(f"  SERVICIO_TH.IDSTH: {r['total']:,} filas, {r['distintos']:,} distintos  "
                  f"{'✅' if r['total'] == r['distintos'] else '⚠️'}")
        except Exception as exc:
            print(f"  ❌ Verificación de llaves falló: {exc}")
            ok = False
    finally:
        cm.__exit__(None, None, None)
    return ok


def _probar_postgres() -> bool:
    _titulo("PostgreSQL (solo lectura) como siger_user")
    ok = True
    try:
        with postgres_cursor(commit=False) as cur:
            cur.execute("SELECT current_user AS usuario, current_database() AS base, version() AS version")
            r = cur.fetchone()
            print(f"  ✅ Conectado como {r['usuario']} a {r['base']}\n  {r['version']}")

            cur.execute("SELECT nspowner::regrole::text AS dueno FROM pg_namespace WHERE nspname = 'siger'")
            r = cur.fetchone()
            if r is None:
                print("  ❌ El esquema siger no existe (debe crearlo un superusuario -- ver sql/11_roles_siger.sql)")
                return False
            ok_dueno = r["dueno"] == "siger_user"
            print(f"  Esquema siger, dueño {r['dueno']}  {'✅' if ok_dueno else '❌ (esperado siger_user)'}")
            ok = ok and ok_dueno

            chequeos = [
                ("CREATE en esquema siger", "SELECT has_schema_privilege('siger', 'CREATE') AS v", True),
                ("USAGE en esquema staging", "SELECT has_schema_privilege('staging', 'USAGE') AS v", True),
                ("SELECT en staging.control_cargas",
                 "SELECT has_table_privilege('staging.control_cargas', 'SELECT') AS v", True),
                ("INSERT en staging.control_cargas",
                 "SELECT has_table_privilege('staging.control_cargas', 'INSERT') AS v", True),
                ("USAGE en la secuencia de control_cargas",
                 "SELECT has_sequence_privilege(pg_get_serial_sequence('staging.control_cargas', 'id'), 'USAGE') AS v",
                 True),
                ("CREATE en la base (no debe tenerlo)",
                 "SELECT has_database_privilege(current_database(), 'CREATE') AS v", False),
                ("mart_user con USAGE en siger",
                 "SELECT has_schema_privilege('mart_user', 'siger', 'USAGE') AS v", True),
            ]
            for nombre, sql, esperado in chequeos:
                try:
                    cur.execute(sql)
                    v = cur.fetchone()["v"]
                except Exception as exc:
                    cur.connection.rollback()
                    print(f"  ❌ {nombre}: {exc}")
                    ok = False
                    continue
                bien = v == esperado
                ok = ok and bien
                print(f"  {nombre}: {v}  {'✅' if bien else '❌'}")

            cur.execute(
                """
                SELECT d.defaclrole::regrole::text AS rol, d.defaclobjtype AS tipo, d.defaclacl::text AS acl
                FROM pg_default_acl d JOIN pg_namespace n ON n.oid = d.defaclnamespace
                WHERE n.nspname = 'siger'
                """
            )
            acls = cur.fetchall()
            ok_acl = any(a["rol"] == "siger_user" and a["tipo"] == "r" and "mart_user=r/" in a["acl"] for a in acls)
            print(f"  Default privileges en siger: {[dict(a) for a in acls] or 'ninguno'}")
            print(f"  SELECT por defecto para mart_user sobre tablas/vistas de siger_user  {'✅' if ok_acl else '❌'}")
            ok = ok and ok_acl

            for rol in ROLES_SIN_ACCESO_A_SIGER:
                cur.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AS existe", (rol,))
                if not cur.fetchone()["existe"]:
                    print(f"  Rol {rol}: no existe (nada que verificar)")
                    continue
                cur.execute("SELECT has_schema_privilege(%s, 'siger', 'USAGE') AS v", (rol,))
                v = cur.fetchone()["v"]
                ok = ok and not v
                print(f"  {rol} sin USAGE en siger: {not v}  {'✅' if not v else '❌'}")
    except Exception as exc:
        print(f"  ❌ Falló la conexión/consulta a PostgreSQL como siger_user: {exc}")
        return False
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba de conectividad y permisos de SIGER_V3 (solo lectura).")
    parser.add_argument("--pg", action="store_true",
                        help="Además, verificar el lado PostgreSQL como siger_user (solo lectura).")
    args = parser.parse_args(argv)

    ok = _probar_sqlserver()
    if args.pg:
        ok = _probar_postgres() and ok

    _titulo("✅ RESULTADO: todo OK" if ok else "❌ RESULTADO: hay problemas -- ver detalle arriba")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
