"""
siger/cargar_siger.py — Carga de SIGER_V3 hacia el esquema siger como
SNAPSHOT COMPLETO POR REEMPLAZO (lección del incidente del 25-sep-2026: el
UPSERT sin borrado dejó filas huérfanas que nadie detectó).

Patrón común para las 4 tablas (cargar_tabla):
  1. Origen: verifica permisos de las columnas exactas (falla nombrando la
     columna denegada), avisa si SIGER expone columnas accesibles nuevas y
     cuenta filas. Nunca SELECT *.
  2. Protección temprana: 0 filas en origen, o caída > UMBRAL_CAIDA_MAXIMA
     respecto al snapshot anterior -> se aborta SIN tocar el destino
     (permitir_caida=True la omite tras revisión humana).
  3. En UNA transacción de siger_user: TRUNCATE + INSERT por lotes
     (fetchmany, nunca fetchall) + certificación ANTES del COMMIT:
       - conteo extraído = conteo insertado (y la misma protección de caída
         con el conteo real),
       - multiconjunto de hashes MD5 en AMBAS direcciones (faltantes y
         sobrantes) recalculado desde lo que quedó en PostgreSQL,
       - hash_contenido guardado = hash recalculado de cada fila.
     Cualquier discrepancia -> ROLLBACK: el snapshot anterior queda intacto.
  4. Registro en staging.control_cargas (tipo_carga siger_*).

Detección de cambios (08-oct-2026, siger/huella_siger.py): antes de extraer
se toma la huella de la tabla en SIGER; si coincide con la del último
snapshot confirmado (siger.huella_fuente), la tabla NO se recarga (estado
SIN_CAMBIOS en control_cargas). Si se recarga, la huella nueva se guarda en
la misma transacción del snapshot.

Sin filtros de servicio, estado ni ELIMINADO: la tabla cruda es copia fiel.
Las reglas de §3 (contrato_key, RUC resuelto, tipo_enlace) se calculan como
columnas derivadas, fuera del hash.

Uso:
    python cargar_siger.py --tabla titulos
    python cargar_siger.py --tabla todas
    python cargar_siger.py --tabla facturacion --permitir-caida
    python cargar_siger.py --tabla todas --forzar     # recarga aunque no haya cambios
"""
import argparse
import logging
from dataclasses import dataclass
from datetime import datetime

from psycopg2.extras import execute_values

from config_siger import (
    COLUMNA_CONTEO,
    COLUMNAS_PERMITIDAS,
    TAMANO_LOTE,
    UMBRAL_CAIDA_MAXIMA,
    columnas_de_origen,
    columnas_denegadas,
    postgres_conexion,
    postgres_cursor,
    sqlserver_conexion,
    sqlserver_cursor,
    verificar_permisos,
)
from hash_siger import digest_fila
from huella_siger import decidir_recarga, guardar_huella, leer_huella, tomar_huella
from reglas import contrato_facturacion, contrato_key, resolver_ruc, thsecuencial_a_bigint, tipo_enlace

logger = logging.getLogger(__name__)


class CargaAbortada(RuntimeError):
    """Protección activada: no se toca (o se revierte) el destino."""


class CertificacionFallida(RuntimeError):
    """Lo insertado no coincide con lo extraído: se revierte la transacción."""


@dataclass(frozen=True)
class Tabla:
    clave: str
    objeto: str
    destino: str
    tipo_carga: str
    derivadas: tuple = ()

    @property
    def columnas(self) -> list[str]:
        """Columnas de ORIGEN (nombres de SIGER), en el orden del SELECT."""
        return COLUMNAS_PERMITIDAS[self.objeto]

    @property
    def columnas_destino(self) -> list[str]:
        """Columnas del INSERT: las de origen en minúscula + las derivadas."""
        return [c.lower() for c in self.columnas] + list(self.derivadas)


# Orden de carga del DAG: facturación necesita los títulos ya cargados
# (tipo_enlace se calcula contra sus contrato_key).
TABLAS = {
    "servicios": Tabla("servicios", "dbo.SERVICIO_TH", "siger.servicio_th", "siger_servicios"),
    "concesionarios": Tabla("concesionarios", "dbo.VISTA_CONCESIONARIOS", "siger.concesionario",
                            "siger_concesionarios", ("ruc_resuelto", "ruc_origen")),
    "titulos": Tabla("titulos", "dbo.TITULO_HABILITANTE", "siger.titulo_habilitante",
                     "siger_titulos", ("contrato_key",)),
    "facturacion": Tabla("facturacion", "dbo.NR_PARAMETROS_FACTURACION", "siger.facturacion_espectro",
                         "siger_facturacion", ("contrato_key", "tipo_enlace")),
}


def _sql_extraccion(tabla: Tabla) -> str:
    return f"SELECT {', '.join(f'[{c}]' for c in tabla.columnas)} FROM {tabla.objeto}"


def _transformador(tabla: Tabla, claves_titulos: set[str] | None = None, derivar: bool = True):
    """
    Devuelve f(valores) que, sobre la lista de valores de origen de UNA fila:
      - rechaza texto con carácter NUL (PostgreSQL no lo admite; no se
        limpia en silencio),
      - convierte THSECUENCIAL a entero (falla si no lo es) -- ANTES del
        hash, para que origen y destino (BIGINT) se hasheen igual,
      - devuelve la tupla de columnas derivadas (vacía si derivar=False,
        como en la validación, que solo certifica columnas de origen).
    """
    cols = tabla.columnas
    pos = {c.upper(): i for i, c in enumerate(cols)}
    objeto = tabla.objeto

    def revisar_nul(valores):
        for i, v in enumerate(valores):
            if v.__class__ is str and "\x00" in v:
                raise ValueError(
                    f"{objeto}.{cols[i]} contiene un carácter NUL (\\x00), que PostgreSQL no admite. "
                    f"No se limpia en silencio: revisar el dato en SIGER."
                )

    if tabla.clave == "titulos":
        i_th, i_tomo, i_foja = pos["THSECUENCIAL"], pos["THTOMO"], pos["THFOJA"]

        def f(v):
            revisar_nul(v)
            v[i_th] = thsecuencial_a_bigint(v[i_th])
            return (contrato_key(v[i_tomo], v[i_foja]),) if derivar else ()
    elif tabla.clave == "concesionarios":
        i_ruc, i_ci = pos["RUC"], pos["CI_RUC"]

        def f(v):
            revisar_nul(v)
            return resolver_ruc(v[i_ruc], v[i_ci]) if derivar else ()
    elif tabla.clave == "facturacion":
        i_contrato = pos["CONTRATO"]
        if derivar and claves_titulos is None:
            raise ValueError("facturacion: faltan las claves de contrato de los títulos para tipo_enlace.")

        def f(v):
            revisar_nul(v)
            if not derivar:
                return ()
            return contrato_facturacion(v[i_contrato]), tipo_enlace(v[i_contrato], claves_titulos)
    else:
        def f(v):
            revisar_nul(v)
            return ()
    return f


def iterar_origen(tabla: Tabla, claves_titulos: set[str] | None = None, derivar: bool = True):
    """
    Recorre el objeto completo de SIGER por lotes (fetchmany de TAMANO_LOTE,
    nunca fetchall) y produce (valores_origen, derivadas, digest) por fila.
    La consulta tiene tiempo límite (TIMEOUT_CONSULTA_S en conn.timeout).
    """
    transformar = _transformador(tabla, claves_titulos, derivar)
    conn = sqlserver_conexion()
    try:
        cur = conn.cursor()
        cur.execute(_sql_extraccion(tabla))
        while True:
            lote = cur.fetchmany(TAMANO_LOTE)
            if not lote:
                break
            for r in lote:
                valores = list(r)
                derivadas = transformar(valores)
                yield valores, derivadas, digest_fila(valores)
    finally:
        conn.close()


def verificar_origen(tabla: Tabla) -> tuple[int, list[str]]:
    """
    Permisos de las columnas exactas (falla nombrando la denegada), columnas
    accesibles que SIGER expone y no se replican (solo aviso: no rompen la
    fidelidad de lo que sí se copia, pero indican que hay que ampliar
    COLUMNAS_PERMITIDAS) y conteo de filas sin referenciar columnas denegadas.
    """
    with sqlserver_cursor() as cur:
        verificar_permisos(cur, tabla.objeto, tabla.columnas)
        usadas = {c.lower() for c in tabla.columnas}
        otras = [m["COLUMN_NAME"] for m in columnas_de_origen(cur, tabla.objeto)
                 if m["COLUMN_NAME"].lower() not in usadas]
        bloqueadas = set(columnas_denegadas(cur, tabla.objeto, otras))
        nuevas_accesibles = [c for c in otras if c not in bloqueadas]
        if nuevas_accesibles:
            logger.warning(
                "%s: SIGER ahora permite consultar columna(s) que no se replican: %s. "
                "Agregarlas a COLUMNAS_PERMITIDAS y a sql/12_ddl_siger.sql.",
                tabla.objeto, nuevas_accesibles,
            )
        cur.execute(f"SELECT COUNT_BIG(*) AS n FROM (SELECT [{COLUMNA_CONTEO[tabla.objeto]}] "
                    f"FROM {tabla.objeto}) t")
        return cur.fetchone()["n"], nuevas_accesibles


def verificar_caida(tabla: Tabla, n_nuevo: int, n_previo: int, permitir_caida: bool) -> None:
    if n_nuevo == 0:
        raise CargaAbortada(
            f"{tabla.objeto}: SIGER devolvió 0 filas -- se aborta sin tocar {tabla.destino} "
            f"(posible falla de la fuente, no una baja real)."
        )
    if n_previo and n_nuevo < n_previo * (1 - UMBRAL_CAIDA_MAXIMA) and not permitir_caida:
        raise CargaAbortada(
            f"{tabla.objeto}: {n_nuevo:,} filas en origen frente a {n_previo:,} del snapshot anterior "
            f"(caída de más del {UMBRAL_CAIDA_MAXIMA:.0%}) -- se aborta sin tocar {tabla.destino}. "
            f"Si la caída es real, revisarla y relanzar con permitir_caida "
            f"(dag_run.conf {{\"permitir_caida\": [\"{tabla.tipo_carga}\"]}})."
        )


def restar_destino(conn, tabla: Tabla, balance: dict) -> tuple[int, int]:
    """
    Recorre el destino con un cursor con nombre (server-side, sin cargar
    todo en memoria), RECALCULA el hash desde los valores guardados y lo
    descuenta de `balance` (que trae +1 por cada fila de origen). Al final,
    balance solo conserva diferencias: >0 faltan en destino, <0 sobran.
    Devuelve (filas_destino, filas cuyo hash_contenido guardado no
    coincide con sus propios valores).
    """
    n = 0
    inconsistentes = 0
    cols = ", ".join(c.lower() for c in tabla.columnas)
    with conn.cursor(name=f"certificar_{tabla.clave}") as cur:
        cur.itersize = TAMANO_LOTE
        cur.execute(f"SELECT {cols}, hash_contenido FROM {tabla.destino}")
        for r in cur:
            d = digest_fila(r[:-1])
            resto = balance.get(d, 0) - 1
            if resto:
                balance[d] = resto
            else:
                balance.pop(d, None)
            if r[-1] != d.hex():
                inconsistentes += 1
            n += 1
    return n, inconsistentes


def resumir_balance(balance: dict) -> tuple[int, int]:
    """(filas faltantes en destino, filas sobrantes en destino) de un balance de hashes."""
    faltantes = sum(v for v in balance.values() if v > 0)
    sobrantes = -sum(v for v in balance.values() if v < 0)
    return faltantes, sobrantes


def _claves_titulos(pg_cur) -> set[str]:
    pg_cur.execute(
        "SELECT DISTINCT upper(contrato_key) FROM siger.titulo_habilitante WHERE contrato_key <> '-'"
    )
    claves = {r[0] for r in pg_cur.fetchall()}
    if not claves:
        raise CargaAbortada(
            "siger.titulo_habilitante está vacía: cargar los títulos antes que la facturación "
            "(tipo_enlace se calcula contra sus contrato_key)."
        )
    return claves


def cargar_tabla(clave: str, permitir_caida: bool = False, forzar: bool = False,
                 dependencia_recargada: bool = False) -> dict:
    """
    Snapshot completo por reemplazo de una tabla de SIGER (ver docstring del
    módulo), solo si la huella cambió (o forzar / dependencia_recargada, ver
    huella_siger.decidir_recarga). Devuelve un dict con "recargada".
    """
    tabla = TABLAS[clave]
    inicio = datetime.now()
    n = 0
    print(f"\n{'=' * 70}\nCARGA SIGER — {tabla.objeto} → {tabla.destino}\n{'=' * 70}")
    try:
        n_origen, nuevas = verificar_origen(tabla)
        print(f"  Permisos OK en {len(tabla.columnas)} columnas; {n_origen:,} filas en origen.")
        # Huella ANTES de extraer: si SIGER cambia durante la extracción, la
        # guardada queda vieja y la próxima corrida recarga.
        huella = tomar_huella(tabla.objeto)

        conn = postgres_conexion()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {tabla.destino}")
            n_previo = cur.fetchone()[0]
            motivo = decidir_recarga(huella, leer_huella(cur, tabla.tipo_carga), n_previo,
                                     forzar, dependencia_recargada)
            if motivo is None:
                conn.rollback()
                print(f"⏭️  {tabla.destino}: sin cambios en SIGER desde el último snapshot "
                      f"({n_previo:,} filas) -- no se recarga.")
                _registrar_carga(tabla.tipo_carga, 0, "SIN_CAMBIOS", None, inicio)
                return {"clave": clave, "tabla": tabla.destino, "recargada": False, "motivo": None,
                        "filas": n_previo, "filas_previas": n_previo,
                        "columnas_nuevas_no_replicadas": nuevas}
            print(f"  Se recarga: {motivo}.")
            verificar_caida(tabla, n_origen, n_previo, permitir_caida)
            claves = _claves_titulos(cur) if clave == "facturacion" else None

            cur.execute(f"TRUNCATE {tabla.destino}")
            sql_insert = (f"INSERT INTO {tabla.destino} ({', '.join(tabla.columnas_destino)}, hash_contenido) "
                          f"VALUES %s")
            balance: dict[bytes, int] = {}
            lote = []
            t0 = datetime.now()
            for valores, derivadas, d in iterar_origen(tabla, claves):
                balance[d] = balance.get(d, 0) + 1
                lote.append((*valores, *derivadas, d.hex()))
                if len(lote) >= TAMANO_LOTE:
                    execute_values(cur, sql_insert, lote, page_size=1000)
                    n += len(lote)
                    lote.clear()
                    if n % (TAMANO_LOTE * 20) == 0:
                        logger.info("%s: %s filas insertadas (%.0fs)", tabla.destino, f"{n:,}",
                                    (datetime.now() - t0).total_seconds())
            if lote:
                execute_values(cur, sql_insert, lote, page_size=1000)
                n += len(lote)
            t_carga = (datetime.now() - t0).total_seconds()
            print(f"  {n:,} filas extraídas e insertadas en {t_carga:.1f}s (sin COMMIT todavía).")

            verificar_caida(tabla, n, n_previo, permitir_caida)

            t1 = datetime.now()
            n_destino, inconsistentes = restar_destino(conn, tabla, balance)
            faltantes, sobrantes = resumir_balance(balance)
            ok = n_destino == n and not faltantes and not sobrantes and not inconsistentes
            print(f"  Certificación previa al COMMIT ({(datetime.now() - t1).total_seconds():.1f}s): "
                  f"{n:,} extraídas / {n_destino:,} en destino, {faltantes} faltantes, {sobrantes} sobrantes, "
                  f"{inconsistentes} hash inconsistentes  {'✅' if ok else '❌'}")
            if not ok:
                raise CertificacionFallida(
                    f"{tabla.destino}: {n:,} filas extraídas vs {n_destino:,} en destino; "
                    f"{faltantes} faltantes, {sobrantes} sobrantes, {inconsistentes} con hash inconsistente "
                    f"-- ROLLBACK, el snapshot anterior queda intacto."
                )
            guardar_huella(cur, tabla.tipo_carga, huella)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        duracion = (datetime.now() - inicio).total_seconds()
        print(f"✅ {tabla.destino}: {n:,} filas (antes {n_previo:,}) en {duracion:.1f}s")
        _registrar_carga(tabla.tipo_carga, n, "EXITOSO", None, inicio)
        logger.info("%s: snapshot de %s filas certificado y confirmado.", tabla.destino, n)
        return {"clave": clave, "tabla": tabla.destino, "recargada": True, "motivo": motivo,
                "filas": n, "filas_previas": n_previo, "columnas_nuevas_no_replicadas": nuevas}

    except Exception as exc:
        print(f"❌ {tabla.destino}: FALLÓ -- {exc}")
        _registrar_carga(tabla.tipo_carga, n, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando %s", tabla.destino)
        raise


def _registrar_carga(tipo_carga, filas, estado, mensaje_error, fecha_inicio):
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES (%s, NULL, %s, NULL, %s, %s, %s)
            """,
            (tipo_carga, filas, estado, mensaje_error, fecha_inicio),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Snapshot por reemplazo de SIGER_V3 hacia el esquema siger.")
    parser.add_argument("--tabla", required=True, choices=[*TABLAS, "todas"])
    parser.add_argument("--permitir-caida", action="store_true",
                        help=f"Omite la protección de caída > {UMBRAL_CAIDA_MAXIMA:.0%} (solo tras revisarla).")
    parser.add_argument("--forzar", action="store_true",
                        help="Recarga aunque la huella de SIGER no haya cambiado.")
    args = parser.parse_args()
    titulos_recargados = False
    for c in (TABLAS if args.tabla == "todas" else [args.tabla]):
        r = cargar_tabla(c, permitir_caida=args.permitir_caida, forzar=args.forzar,
                         dependencia_recargada=(c == "facturacion" and titulos_recargados))
        titulos_recargados = titulos_recargados or (c == "titulos" and r["recargada"])
