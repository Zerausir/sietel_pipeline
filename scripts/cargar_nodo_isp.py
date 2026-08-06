"""
Carga de la dimensión versionada (SCD Tipo 2): NodoISP.

Mismo criterio que scripts/cargar_dimensiones.py (dim_isp, dim_permiso_va_agregado):
SQL Server (SIETEL) solo expone el estado ACTUAL de dbo.NodoISP -- no existe
fuente para el valor histórico real anterior al arranque de este pipeline.
Ver advertencia en sql/01_ddl_postgres.sql, sección 8.

Fuente: dbo.NodoISP exclusivamente. dbo.NodoISP_Auxiliar queda deliberadamente
fuera -- EDA dirigido (06-ago-2026) confirmó que está congelada desde
2014-07-03 y que sus 366 peva_codigo ya están cubiertos por NodoISP (cero
PEVA exclusivos de Auxiliar). Es un remanente de migración, no una fuente
paralela viva. Si en el futuro aparece evidencia de lo contrario, este
archivo es el lugar para reconsiderarlo -- no reintroducirla sin repetir
ese EDA.

Columnas que disparan una nueva versión (atributos "Tipo 2") se definen
explícitamente abajo, mismo criterio que cargar_dimensiones.py: columnas de
metadata técnica no versionan, solo hechos de negocio.

IMPORTANTE: esta lista de columnas versionables es una propuesta inicial del
equipo técnico, igual que COLUMNAS_VERSIONABLES_ISP/PERMISO. Debe
confirmarse/ajustarse con el área de Mercados antes de considerarse
definitiva.

Alcance de Capa 1 (este archivo): extraer y certificar tal cual lo reporta
SIETEL. latitud/longitud viajan como texto libre (formato DMS potencialmente
sucio) sin ninguna limpieza ni conversión -- eso es responsabilidad de
Capa 2/3 (mart), igual que el resto de la lógica de negocio de este pipeline.

CAMBIO 07-ago-2026: se agregó el JOIN contra dbo.Parroquia/Ciudad/Provincia
para traer codigo_parroquia/codigo_canton/codigo_provincia (códigos INEC,
no confundir con par_codigo/ciu_codigo/pro_codigo que son PKs internas de
SIETEL). Faltaban en la versión original -- detectados como necesarios recién
al diseñar mart/detectar_discrepancias_geografia_nodo.py (Parte B), que
compara estos códigos contra DPA_PARROQ del shapefile CONALI. Mismo patrón
de LEFT JOIN sin FK declarada que ya se usó en la consulta ad hoc de ADEATEL
S.A. -- de las tres relaciones, solo NodoISP.par_codigo -> Parroquia.par_codigo
carece de FK real; Parroquia.ciu_codigo -> Ciudad (FK_Parroquia_Ciudad) y
Ciudad.pro_codigo -> Provincia (FK_Ciudad_Provincia) sí están declaradas. Un
par_codigo huérfano en NodoISP deja estos campos en NULL, visible, en vez de
perder la fila -- por eso los tres JOIN son LEFT, no INNER.
"""
import logging
from datetime import datetime

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

# Columnas de negocio que, al cambiar, disparan el cierre de la versión
# vigente y la apertura de una nueva.
COLUMNAS_VERSIONABLES_NODO_ISP = [
    "par_codigo", "estado", "tipoNodo", "latitud", "longitud", "verificado",
]

SQL_EXTRAER_NODO_ISP = """
    SELECT
        n.noisp_codigo, n.peva_codigo, n.par_codigo, n.noisp_nombre,
        n.noisp_fechaInicio, n.noisp_oficioSenatel, n.estado, n.tipoNodo,
        n.direccion, n.latitud, n.longitud, n.verificado, n.observacion,
        n.regional, n.fechaModificacion,
        par.par_nombre, par.codigoParroquia AS codigo_parroquia,
        ciu.ciu_nombre, ciu.codigoCiudad AS codigo_canton,
        prov.pro_nombre, prov.codigo AS codigo_provincia
    FROM dbo.NodoISP n
    LEFT JOIN dbo.Parroquia par ON par.par_codigo = n.par_codigo
    LEFT JOIN dbo.Ciudad ciu ON ciu.ciu_codigo = par.ciu_codigo
    LEFT JOIN dbo.Provincia prov ON prov.pro_codigo = ciu.pro_codigo
"""


def _extraer_filas(cursor, sql):
    cursor.execute(sql)
    return cursor.fetchall()


def _obtener_vigentes(pg_cursor, tabla, llave_natural):
    pg_cursor.execute(
        f"SELECT * FROM staging.{tabla} WHERE es_vigente = true"
    )
    filas = pg_cursor.fetchall()
    return {fila[llave_natural]: fila for fila in filas}


def _cambio_relevante(fila_origen: dict, fila_vigente: dict, columnas: list) -> bool:
    """
    Comparación insensible a mayúsculas/minúsculas en las CLAVES (no en los
    valores). fila_origen viene de SQL Server (pyodbc preserva el case
    exacto de la columna, ej. "tipoNodo"); fila_vigente viene de Postgres
    (RealDictCursor devuelve las claves tal como Postgres las guarda -- y
    Postgres pliega a minúsculas cualquier identificador sin comillas del
    CREATE TABLE, ej. "tipoNodo" se guarda como "tiponodo"). Sin este
    normalizado, fila_vigente.get("tipoNodo") siempre da None (la clave real
    es "tiponodo"), y None != <valor real> dispara "cambio relevante" para
    TODAS las filas, siempre -- confirmado en producción 07-ago-2026 con
    dim_nodo_isp (8606 "cambios" que no eran reales) y con el mismo patrón
    ya presente en COLUMNAS_VERSIONABLES_PERMISO de cargar_dimensiones.py
    (nombreComercial/Resolucion).
    """
    origen_lower = {k.lower(): v for k, v in fila_origen.items()}
    vigente_lower = {k.lower(): v for k, v in fila_vigente.items()}
    for col in columnas:
        if origen_lower.get(col.lower()) != vigente_lower.get(col.lower()):
            return True
    return False


def cargar_dim_nodo_isp():
    inicio = datetime.now()
    insertadas = 0
    actualizadas = 0
    try:
        with sqlserver_cursor() as ms_cur, postgres_cursor() as pg_cur:
            filas_origen = _extraer_filas(ms_cur, SQL_EXTRAER_NODO_ISP)
            vigentes = _obtener_vigentes(pg_cur, "dim_nodo_isp", "noisp_codigo")

            for fila in filas_origen:
                vigente = vigentes.get(fila["noisp_codigo"])

                if vigente is None:
                    # Nodo nunca cargado: primera versión. fecha_inicio_vigencia
                    # se fija deliberadamente muy en el pasado (no now()), mismo
                    # criterio que cargar_dim_isp/cargar_dim_permiso_va_agregado,
                    # para que cualquier vista futura que necesite unir por
                    # fecha (ej. geografía del nodo al momento de un reporte)
                    # pueda hacerlo sin huérfanos.
                    pg_cur.execute(
                        """
                        INSERT INTO staging.dim_nodo_isp
                            (noisp_codigo, peva_codigo, par_codigo, noisp_nombre,
                             noisp_fechaInicio, noisp_oficioSenatel, estado, tipoNodo,
                             direccion, latitud, longitud, verificado, observacion,
                             regional, fechaModificacion,
                             par_nombre, codigo_parroquia, ciu_nombre, codigo_canton,
                             pro_nombre, codigo_provincia, fecha_inicio_vigencia)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, '1900-01-01')
                        """,
                        (
                            fila["noisp_codigo"], fila["peva_codigo"], fila["par_codigo"],
                            fila["noisp_nombre"], fila["noisp_fechaInicio"],
                            fila["noisp_oficioSenatel"], fila["estado"], fila["tipoNodo"],
                            fila["direccion"], fila["latitud"], fila["longitud"],
                            fila["verificado"], fila["observacion"], fila["regional"],
                            fila["fechaModificacion"],
                            fila["par_nombre"], fila["codigo_parroquia"],
                            fila["ciu_nombre"], fila["codigo_canton"],
                            fila["pro_nombre"], fila["codigo_provincia"],
                        ),
                    )
                    insertadas += 1
                    continue

                if _cambio_relevante(fila, vigente, COLUMNAS_VERSIONABLES_NODO_ISP):
                    # Cierra la versión vigente y abre una nueva
                    pg_cur.execute(
                        """
                        UPDATE staging.dim_nodo_isp
                        SET fecha_fin_vigencia = now(), es_vigente = false
                        WHERE noisp_sk = %s
                        """,
                        (vigente["noisp_sk"],),
                    )
                    pg_cur.execute(
                        """
                        INSERT INTO staging.dim_nodo_isp
                            (noisp_codigo, peva_codigo, par_codigo, noisp_nombre,
                             noisp_fechaInicio, noisp_oficioSenatel, estado, tipoNodo,
                             direccion, latitud, longitud, verificado, observacion,
                             regional, fechaModificacion,
                             par_nombre, codigo_parroquia, ciu_nombre, codigo_canton,
                             pro_nombre, codigo_provincia)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            fila["noisp_codigo"], fila["peva_codigo"], fila["par_codigo"],
                            fila["noisp_nombre"], fila["noisp_fechaInicio"],
                            fila["noisp_oficioSenatel"], fila["estado"], fila["tipoNodo"],
                            fila["direccion"], fila["latitud"], fila["longitud"],
                            fila["verificado"], fila["observacion"], fila["regional"],
                            fila["fechaModificacion"],
                            fila["par_nombre"], fila["codigo_parroquia"],
                            fila["ciu_nombre"], fila["codigo_canton"],
                            fila["pro_nombre"], fila["codigo_provincia"],
                        ),
                    )
                    actualizadas += 1
                else:
                    # Sin cambio en columnas versionables: actualiza en sitio los
                    # atributos no versionables (Tipo 1) de la fila vigente,
                    # incluidos los códigos INEC -- son metadata derivada de
                    # par_codigo (que sí es versionable), mismo criterio que
                    # codigo_provincia/codigo_ciudad/codigo_parroquia en
                    # va_lineas_dedicadas_resumen: se refrescan libremente, no
                    # forman parte de ninguna llave natural.
                    pg_cur.execute(
                        """
                        UPDATE staging.dim_nodo_isp
                        SET noisp_nombre = %s, direccion = %s, observacion = %s,
                            regional = %s, fechaModificacion = %s,
                            par_nombre = %s, codigo_parroquia = %s,
                            ciu_nombre = %s, codigo_canton = %s,
                            pro_nombre = %s, codigo_provincia = %s
                        WHERE noisp_sk = %s
                        """,
                        (
                            fila["noisp_nombre"], fila["direccion"], fila["observacion"],
                            fila["regional"], fila["fechaModificacion"],
                            fila["par_nombre"], fila["codigo_parroquia"],
                            fila["ciu_nombre"], fila["codigo_canton"],
                            fila["pro_nombre"], fila["codigo_provincia"],
                            vigente["noisp_sk"],
                        ),
                    )

        _registrar_carga(
            "nodo_isp", None, insertadas, actualizadas, "EXITOSO", None, inicio
        )
        logger.info(
            "dim_nodo_isp: %s nodos nuevos, %s nuevas versiones por cambio",
            insertadas, actualizadas,
        )
    except Exception as exc:
        _registrar_carga("nodo_isp", None, insertadas, actualizadas, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando dim_nodo_isp")
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
    cargar_dim_nodo_isp()
