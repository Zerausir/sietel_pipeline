"""
Tests unitarios (sin base de datos) del paquete siger/ (SIGER_V3).

Fase 1: constantes de configuración y la normalización de RUC compartida
con mart/detectar_conflictos_peva.py. Las reglas de datos (contrato_key,
resolver_ruc, tipo_enlace, hash) se agregan en la fase 2.

Uso:
    python -m pytest tests/
"""
import os
import sys

RAIZ = os.path.join(os.path.dirname(__file__), "..")
for carpeta in ("mart", "scripts", "siger"):
    sys.path.insert(0, os.path.join(RAIZ, carpeta))

from config_siger import COLUMNAS_PERMITIDAS, IDSTH_UNIVERSO_SAI  # noqa: E402
from detectar_conflictos_peva import SQL_PARES_CANDIDATOS, SQL_RUC_LIMPIO  # noqa: E402


def test_ruc_limpio_es_la_expresion_del_detector():
    esperado = "NULLIF(REGEXP_REPLACE(COALESCE(v.isp_ruc::text, ''), '[^0-9]', '', 'g'), '') AS ruc_limpio"
    assert SQL_RUC_LIMPIO.format(col="v.isp_ruc") + " AS ruc_limpio" == esperado
    assert esperado in SQL_PARES_CANDIDATOS


def test_universo_sai_excluye_valor_agregado():
    assert set(IDSTH_UNIVERSO_SAI) == {9, 33, 31}
    assert 8 not in IDSTH_UNIVERSO_SAI


def test_columnas_denegadas_no_se_usan():
    # Bloqueadas según la prueba real en VM2 (05-oct-2026).
    denegadas_titulo = {
        "THPAGINA", "THACTA", "THUSUARIO", "TTHSECUENCIAL", "STHSECUENCIAL",
        "THRESOLUCION", "THFECHARES", "THTITULO", "THCUERPO", "THCOBERTURA",
        "THUSUARIOREG", "THFECHAREG", "THNUMERO_TRAMITE", "THCONTRATO_RENOVADO",
    }
    titulo = {c.upper() for c in COLUMNAS_PERMITIDAS["dbo.TITULO_HABILITANTE"]}
    assert not denegadas_titulo & titulo
    assert "THFECHASUS" in titulo  # accesible hoy: se replica
    assert not {"IDTSV", "ELIMINACION"} & {c.upper() for c in COLUMNAS_PERMITIDAS["dbo.SERVICIO_TH"]}
    assert COLUMNAS_PERMITIDAS["dbo.VISTA_CONCESIONARIOS"] == ["ucp_concnum", "nombres", "ci_ruc", "ruc"]
    facturacion = COLUMNAS_PERMITIDAS["dbo.NR_PARAMETROS_FACTURACION"]
    assert len(facturacion) == 99 and len(set(facturacion)) == 99


class _CursorSimulado:
    """Simula pyodbc: falla (error 230) si la consulta menciona una columna denegada."""

    def __init__(self, denegadas):
        self.denegadas = denegadas

    def execute(self, sql, *args):
        if any(f"[{c}]" in sql for c in self.denegadas):
            raise Exception("(230) The SELECT permission was denied on the column")

    def fetchall(self):
        return []


def test_verificar_permisos_usa_prueba_real_por_columna():
    import pytest
    from config_siger import PermisoDenegado, columnas_denegadas, verificar_permisos

    cur = _CursorSimulado({"THPAGINA"})
    assert columnas_denegadas(cur, "dbo.T", ["THSECUENCIAL", "THPAGINA", "THACTA"]) == ["THPAGINA"]
    with pytest.raises(PermisoDenegado, match="THPAGINA"):
        verificar_permisos(cur, "dbo.T", ["THSECUENCIAL", "THPAGINA"])
    verificar_permisos(_CursorSimulado(set()), "dbo.T", ["THSECUENCIAL", "THACTA"])


# ── Fase 2: reglas de datos (§3) ─────────────────────────────────────────────

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from cargar_siger import TABLAS, _transformador, resumir_balance  # noqa: E402
from hash_siger import digest_fila, valor_para_hash  # noqa: E402
from reglas import contrato_key, resolver_ruc, thsecuencial_a_bigint, tipo_enlace  # noqa: E402


def test_contrato_key_texto_y_vacios():
    assert contrato_key("010", "13708A") == "010-13708A"       # ceros y sufijos se conservan
    assert contrato_key(" 95 ", "9579  ") == "95-9579"          # LTRIM/RTRIM
    assert contrato_key("", "") == "-"                          # sin tomo-foja
    assert contrato_key(None, None) == "-"                      # supuesto: NULL = vacío
    assert contrato_key("08", "08f02v") == "08-08f02v"
    assert contrato_key("\t1", "2") == "\t1-2"                  # solo espacios, como LTRIM


def test_resolver_ruc_cuatro_ramas():
    assert resolver_ruc("1790012345001", "1712345678") == ("1790012345001", "ruc")
    assert resolver_ruc("1790012345001", None) == ("1790012345001", "ruc")
    assert resolver_ruc("             ", "0990012345001") == ("0990012345001", "ci_ruc_13")  # char con relleno
    assert resolver_ruc(None, " 1712345678 ") == ("1712345678001", "cedula_001")
    assert resolver_ruc("ABC", "12345") == (None, "sin_ruc")
    assert resolver_ruc(None, None) == (None, "sin_ruc")


def test_tipo_enlace_orden():
    claves = {"95-9579", "010-08F02V"}
    assert tipo_enlace(None, claves) == "SIN_CONTRATO"
    assert tipo_enlace("   ", claves) == "SIN_CONTRATO"
    assert tipo_enlace(" 95-9579 ", claves) == "TOMO_FOJA"
    assert tipo_enlace("010-08f02v", claves) == "TOMO_FOJA"     # sin distinguir mayúsculas
    assert tipo_enlace("ARCOTEL-2024-0001", claves) == "TRAMITE"
    assert tipo_enlace("99-1", claves) == "SIN_MATCH"


def test_thsecuencial_entero_o_falla():
    assert thsecuencial_a_bigint(123.0) == 123
    with pytest.raises(ValueError):
        thsecuencial_a_bigint(1.5)
    with pytest.raises(ValueError):
        thsecuencial_a_bigint(None)


def test_hash_estable_por_tipo():
    assert valor_para_hash(True) == "1" and valor_para_hash(False) == "0"
    assert valor_para_hash(5) == "5" and valor_para_hash(None) == "NULL"
    assert valor_para_hash(0.1) == "0.1"
    assert valor_para_hash(datetime(2026, 10, 5, 8, 30, 0, 3000)) == "2026-10-05T08:30:00.003000"
    assert digest_fila([1, "a ", None]) == digest_fila([1, "a ", None])
    assert digest_fila([1, "a ", None]) != digest_fila([1, "a", None])  # el relleno cuenta: copia fiel
    with pytest.raises(TypeError):
        valor_para_hash(object())


def test_transformador_titulos_convierte_antes_del_hash():
    t = TABLAS["titulos"]
    fila = [None] * len(t.columnas)
    pos = {c: i for i, c in enumerate(t.columnas)}
    fila[pos["THSECUENCIAL"]], fila[pos["THTOMO"]], fila[pos["THFOJA"]] = 42.0, "010 ", "7"
    assert _transformador(t)(fila) == ("010-7",)
    assert fila[pos["THSECUENCIAL"]] == 42 and isinstance(fila[pos["THSECUENCIAL"]], int)
    assert len(t.columnas_destino) == len(t.columnas) + 1


def test_transformador_rechaza_nul():
    t = TABLAS["servicios"]
    with pytest.raises(ValueError, match="NUL"):
        _transformador(t)([1, "AB\x00", "desc"])


def test_transformador_facturacion_exige_claves():
    with pytest.raises(ValueError):
        _transformador(TABLAS["facturacion"], None, derivar=True)
    assert _transformador(TABLAS["facturacion"], None, derivar=False)([None] * 99) == ()


def test_resumir_balance_ambas_direcciones():
    assert resumir_balance({}) == (0, 0)
    assert resumir_balance({b"a": 2, b"b": -1, b"c": -3}) == (2, 4)


def test_cruce_usa_la_misma_normalizacion_de_ruc():
    from construir_cruce_obtel import SQL_UPSERT_HALLAZGOS
    assert SQL_RUC_LIMPIO.format(col="v.isp_ruc") in SQL_UPSERT_HALLAZGOS
    assert SQL_RUC_LIMPIO.format(col="p.ruc_resuelto") in SQL_UPSERT_HALLAZGOS


# ── Detección de cambios (huella_siger) ──────────────────────────────────────

from huella_siger import decidir_recarga, firma_columnas, sql_huella  # noqa: E402

_HUELLA = {"filas": 100, "checksum": 12345, "columnas": "abc"}


def test_sin_cambios_no_recarga():
    assert decidir_recarga(dict(_HUELLA), dict(_HUELLA), n_destino=100) is None


@pytest.mark.parametrize("actual, guardada, n_destino, kwargs, esperado", [
    (_HUELLA, None, 100, {}, "sin huella"),
    (_HUELLA, _HUELLA, 100, {"forzar": True}, "forzada"),
    ({**_HUELLA, "columnas": "xyz"}, _HUELLA, 100, {}, "columnas"),
    ({**_HUELLA, "filas": 101}, _HUELLA, 100, {}, "conteo"),
    ({**_HUELLA, "checksum": 999}, _HUELLA, 100, {}, "checksum"),
    (_HUELLA, _HUELLA, 0, {}, "destino"),
    (_HUELLA, _HUELLA, 100, {"dependencia_recargada": True}, "depende"),
])
def test_motivos_de_recarga(actual, guardada, n_destino, kwargs, esperado):
    assert esperado in decidir_recarga(actual, guardada, n_destino, **kwargs)


def test_huella_solo_usa_columnas_permitidas():
    sql = sql_huella("dbo.VISTA_CONCESIONARIOS")
    assert "SELECT [ucp_concnum], [nombres], [ci_ruc], [ruc] FROM dbo.VISTA_CONCESIONARIOS" in sql
    assert "*)" in sql and "SELECT *" not in sql
    assert firma_columnas("dbo.SERVICIO_TH") != firma_columnas("dbo.TITULO_HABILITANTE")
