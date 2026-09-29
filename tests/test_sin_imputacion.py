"""
Tests sin base de datos del principio "nunca imputar" (29-sep-2026): capa2
y mart contienen exclusivamente lo que los prestadores reportaron.

Complementan la invariante bloqueante 17.9 de sql/02_ddl_mart.sql (que
revisa las columnas ya creadas en la base): estos tests fallan antes, en
el código, si alguien reintroduce el relleno LOCF o columnas de imputación.

Uso:
    python -m pytest tests/
"""
import os
import re
import sys

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "mart"))

from construir_capa2 import _sentencias_construccion  # noqa: E402

# Rastros del relleno LOCF que existía antes en construir_capa2.py.
PATRON_LOCF = re.compile(r"FIRST_VALUE|LAST_VALUE|generate_series|grupo_carry|\bspine\b", re.IGNORECASE)
PATRON_IMPUTACION = re.compile(r"imput|es_reportado|tiene_imputacion", re.IGNORECASE)


def _sin_comentarios_ni_literales(sql: str) -> str:
    # Una sola pasada, en orden: un literal puede contener "--" (ej. los
    # COMMENT ON VIEW) y un comentario puede contener comillas.
    return re.sub(r"'(?:[^']|'')*'|--[^\n]*", lambda m: "''" if m.group(0).startswith("'") else "", sql)


def test_capa2_no_rellena_huecos():
    sql = "\n".join(_sentencias_construccion())
    assert not PATRON_LOCF.search(sql)


def test_capa2_no_marca_imputacion():
    sql = _sin_comentarios_ni_literales("\n".join(_sentencias_construccion()))
    assert not PATRON_IMPUTACION.search(sql)


def test_mart_sin_columnas_de_imputacion():
    with open(os.path.join(RAIZ, "sql", "02_ddl_mart.sql"), encoding="utf-8") as f:
        sql = _sin_comentarios_ni_literales(f.read())
    hallazgos = sorted(set(m.group(0) for m in re.finditer(r"\w*(?:imput|es_reportado)\w*", sql, re.IGNORECASE)))
    assert hallazgos == []


def test_mart_verifica_sin_imputacion_de_forma_bloqueante():
    # La invariante 17.9 debe seguir dentro del bloque bloqueante (antes del
    # COMMIT) y revisar pg_attribute: information_schema.columns no lista
    # las vistas materializadas.
    with open(os.path.join(RAIZ, "sql", "02_ddl_mart.sql"), encoding="utf-8") as f:
        sql = f.read()
    bloque = sql[sql.index("17.0. INVARIANTES BLOQUEANTES"):sql.index("\nCOMMIT;")]
    assert "17.9" in bloque and "pg_attribute" in bloque and "%imput%" in bloque
