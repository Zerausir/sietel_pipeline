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
    denegadas_titulo = {
        "THUSUARIO", "TTHSECUENCIAL", "STHSECUENCIAL", "THFECHASUS", "THRESOLUCION",
        "THFECHARES", "THTITULO", "THCUERPO", "THCOBERTURA", "THUSUARIOREG",
        "THFECHAREG", "THNUMERO_TRAMITE", "THCONTRATO_RENOVADO",
    }
    assert not denegadas_titulo & {c.upper() for c in COLUMNAS_PERMITIDAS["dbo.TITULO_HABILITANTE"]}
    assert not {"IDTSV", "ELIMINACION"} & {c.upper() for c in COLUMNAS_PERMITIDAS["dbo.SERVICIO_TH"]}
    assert len(COLUMNAS_PERMITIDAS["dbo.VISTA_CONCESIONARIOS"]) == 22


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
