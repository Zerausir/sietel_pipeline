"""
Tests sin base de datos de scripts/detectar_cambios.py (30-sep-2026): qué
meses se recargan cuando SIETEL tiene información nueva, corregida o
eliminada, y cómo se agrupan en lotes por año para el DAG.

Uso:
    python -m pytest tests/
"""
import os
import sys
from datetime import datetime

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

from detectar_cambios import _normalizar, agrupar_por_anio, comparar_huellas  # noqa: E402


def _fila(anio, mes, filas=100, suma=500, checksum=12345, fuente="lineas", max_fecha=None):
    return {"fuente": fuente, "anio": anio, "periodo_numero": mes, "filas": filas,
            "suma": suma, "checksum": checksum, "max_fecha": max_fecha}


GUARDADA = [_fila(2025, 11), _fila(2025, 12), _fila(2026, 1),
            _fila(2025, 4, fuente="formularios", max_fecha="2026-01-10T08:00:00")]


def test_sin_cambios():
    assert comparar_huellas(list(GUARDADA), GUARDADA) == {"periodos": [], "formularios": False}


def test_mes_nuevo_solo_ese_mes():
    cambios = comparar_huellas(GUARDADA + [_fila(2026, 2)], GUARDADA)
    assert cambios == {"periodos": [[2026, 2]], "formularios": False}


def test_mes_corregido_de_anio_anterior():
    actual = [_fila(2025, 11), _fila(2025, 12, checksum=999), _fila(2026, 1), GUARDADA[3]]
    assert comparar_huellas(actual, GUARDADA)["periodos"] == [[2025, 12]]


def test_mes_eliminado_en_origen():
    actual = [f for f in GUARDADA if (f["anio"], f["periodo_numero"]) != (2026, 1)]
    assert comparar_huellas(actual, GUARDADA)["periodos"] == [[2026, 1]]


def test_formulario_modificado_no_recarga_meses_de_hechos():
    actual = GUARDADA[:3] + [_fila(2025, 4, fuente="formularios", max_fecha="2026-03-02T09:30:00")]
    assert comparar_huellas(actual, GUARDADA) == {"periodos": [], "formularios": True}


def test_misma_clave_en_otra_fuente_no_se_confunde():
    # (2025, 4) de formularios no debe compararse contra (2025, 4) de lineas.
    guardada = GUARDADA + [_fila(2025, 4)]
    assert comparar_huellas(list(guardada), guardada) == {"periodos": [], "formularios": False}


def test_agrupar_por_anio():
    periodos = [[2026, 2], [2025, 12], [2026, 1], [2026, 2]]
    assert agrupar_por_anio(periodos) == [{"anio": 2025, "meses": [12]},
                                          {"anio": 2026, "meses": [1, 2]}]
    assert agrupar_por_anio([]) == []


def test_normalizar_iguala_sqlserver_y_postgres():
    # pyodbc y psycopg2 devuelven tipos distintos para el mismo valor.
    sqlserver = _normalizar({"fuente": "formularios", "anio": 2025, "periodo_numero": 4, "filas": 3,
                             "suma": None, "checksum": -7, "max_fecha": datetime(2026, 1, 10, 8, 0)})
    postgres = _normalizar({"fuente": "formularios", "anio": 2025, "periodo_numero": 4, "filas": 3,
                            "suma": None, "checksum": -7, "max_fecha": datetime(2026, 1, 10, 8, 0)})
    assert sqlserver == postgres
    assert sqlserver["max_fecha"] == "2026-01-10T08:00:00"
