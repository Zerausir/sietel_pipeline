"""
mart/limpiar_coordenadas_nodo_isp.py

Parte A del geoprocesamiento de nodos ISP (conversación 06-ago-2026):
convierte latitud/longitud de analitico.v_nodo_isp_vigente (texto libre,
formato DMS inconsistente, copiado tal cual de dbo.NodoISP) a decimal, y
valida contra el bounding box de Ecuador.

Parte B (pendiente): cruce espacial punto-en-polígono contra el shapefile
de parroquias de CONALI (ORGANIZACION_TERRITORIAL_PARROQUIAL), para
comparar la parroquia derivada de la coordenada contra par_codigo/
codigo_parroquia reportado. Esta Parte A es independiente y no la bloquea.

PRINCIPIO DELIBERADO: NO se aplica ninguna "corrección automática" de
coordenadas (ej. dividir por 10000 cuando el valor parece fuera de rango).
Ese tipo de ajuste es una suposición sobre la intención del capturista, no
un hecho verificado -- y el principio central de este pipeline es nunca
alterar en silencio un dato oficialmente reportado. Una coordenada que no
se puede convertir, o que cae fuera del bounding box de Ecuador, se marca
es_coordenada_valida = false con el motivo -- para revisión, no se
"arregla" sola.

Uso:
    python limpiar_coordenadas_nodo_isp.py --dry-run
    python limpiar_coordenadas_nodo_isp.py
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Bounding box de Ecuador, continental + insular -- el límite occidental de
# longitud es más amplio que el continente (-81) para no descartar de
# entrada coordenadas legítimas de Galápagos (~-92 a -89).
LATITUD_MIN, LATITUD_MAX = -5.0, 1.5
LONGITUD_MIN, LONGITUD_MAX = -92.0, -75.0


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def _engine():
    url = URL.create(
        drivername="postgresql+psycopg",
        username=_require_env("MART_USER_USER"),
        password=_require_env("MART_USER_PASSWORD"),
        host=_require_env("ANALITICO_PG_HOST"),
        port=int(os.environ.get("ANALITICO_PG_PORT", "5432")),
        database=os.environ.get("ANALITICO_PG_DATABASE", "sietel_analitico"),
    )
    return create_engine(url, connect_args={"connect_timeout": 10})


_PATRON_NUMEROS = re.compile(r"\d+(?:[.,]\d+)?")


def convertir_dms_a_decimal(valor: str | None) -> tuple[float | None, str | None]:
    """
    Convierte una coordenada en formato DMS (grados/minutos/segundos) libre
    a decimal. Devuelve (valor_decimal, motivo_error): si motivo_error no
    es None, valor_decimal es None -- nunca se adivina un valor aproximado.

    Formatos observados en dbo.NodoISP (nvarchar(20), texto libre de
    captura manual): con o sin símbolos de grado/minuto/segundo, coma o
    punto como separador decimal, letra de hemisferio en cualquier
    posición, 1 a 3 componentes numéricos.
    """
    if valor is None:
        return None, "valor_nulo"

    texto = valor.strip()
    if not texto or texto.lower() in ("nan", "null", "none", "0", "-"):
        return None, "valor_vacio_o_cero"

    texto_upper = texto.upper()
    # S (sur) u O/W (oeste) -> negativo. N/E son positivos por defecto, no
    # requieren acción -- si no hay ninguna letra de hemisferio, se asume
    # positivo tal cual viene (no hay forma de saber la intención sin ella).
    negativo = "S" in texto_upper or "O" in texto_upper or "W" in texto_upper

    numeros = _PATRON_NUMEROS.findall(texto.replace(",", "."))
    if not numeros:
        return None, "sin_componentes_numericos"

    try:
        partes = [float(n) for n in numeros]
    except ValueError:
        return None, "componente_no_numerico"

    grados = partes[0]
    minutos = partes[1] if len(partes) > 1 else 0.0
    segundos = partes[2] if len(partes) > 2 else 0.0

    if not (0 <= minutos < 60) or not (0 <= segundos < 60):
        return None, "minutos_o_segundos_fuera_de_rango_0_60"

    decimal = grados + minutos / 60 + segundos / 3600
    if negativo:
        decimal = -decimal

    return decimal, None


def _validar_rango(lat: float | None, lon: float | None) -> tuple[bool, str | None]:
    if lat is None or lon is None:
        return False, "coordenada_no_convertible"
    if not (LATITUD_MIN <= lat <= LATITUD_MAX):
        return False, f"latitud_fuera_de_rango_ecuador({lat:.4f})"
    if not (LONGITUD_MIN <= lon <= LONGITUD_MAX):
        return False, f"longitud_fuera_de_rango_ecuador({lon:.4f})"
    return True, None


_PATRON_LETRA_HEMISFERIO = re.compile(r"[NSOEW]", re.IGNORECASE)


def inferir_hemisferio_longitud_faltante(texto_original: str, lon_decimal: float | None) -> tuple[float | None, bool]:
    """
    CASO DISTINTO de una "corrección automática" (ver principio del
    docstring del módulo) -- esto no es adivinar la intención de una
    captura ambigua, es aplicar un hecho geográfico verdadero el 100% de
    las veces para este dataset: SIETEL es exclusivamente Ecuador, y
    Ecuador está enteramente al oeste del meridiano de Greenwich (longitud
    siempre negativa, continental e insular). Si el texto original NO trae
    ninguna letra de hemisferio (N/S/E/O/W en ninguna posición) y el valor
    convertido salió positivo, se infiere el signo negativo.

    NUNCA se aplica si el texto SÍ trae una letra de hemisferio, aunque esa
    letra produzca un valor fuera de rango (ej. alguien escribió "E" por
    error) -- ahí hay una señal explícita de la persona que capturó el
    dato, y confiamos en ella tal cual, correcta o no; solo se completa la
    ausencia total de señal, nunca se corrige una señal presente.

    Confirmado en producción 07-ago-2026: 54 nodos con longitud sin letra
    de hemisferio (de 159 inválidos por rango) -- ver diagnóstico manual
    contra capa2.nodo_isp_geocodificado.longitud_original. Deliberadamente
    NO se aplica el mismo criterio a latitud: Ecuador cruza la línea
    ecuatorial, así que una latitud positiva cerca de 0 sin letra puede ser
    Norte genuino -- ahí sí sería adivinar, no aplicar un hecho.

    Devuelve (valor_corregido, se_infirio_signo).
    """
    if lon_decimal is None or lon_decimal <= 0:
        return lon_decimal, False
    if _PATRON_LETRA_HEMISFERIO.search(texto_original or ""):
        return lon_decimal, False
    return -lon_decimal, True


def _sentencias_ddl() -> list[str]:
    return [
        "CREATE SCHEMA IF NOT EXISTS capa2;",
        "DROP TABLE IF EXISTS capa2.nodo_isp_geocodificado;",
        """
        CREATE TABLE capa2.nodo_isp_geocodificado (
            noisp_codigo         VARCHAR(50)  PRIMARY KEY,
            peva_codigo          VARCHAR(50)  NOT NULL,
            par_codigo           VARCHAR(50),
            noisp_nombre         VARCHAR(50),
            tiponodo              VARCHAR(50),
            estado                VARCHAR(50),
            direccion             TEXT,
            verificado_sietel     VARCHAR(2),
            latitud_original      VARCHAR(20),
            longitud_original     VARCHAR(20),
            latitud_decimal       DOUBLE PRECISION,
            longitud_decimal      DOUBLE PRECISION,
            hemisferio_longitud_inferido BOOLEAN NOT NULL DEFAULT false,
            es_coordenada_valida  BOOLEAN NOT NULL,
            motivo_invalida       TEXT,
            fecha_procesado       TIMESTAMP NOT NULL DEFAULT now()
        );
        """,
        "CREATE INDEX ON capa2.nodo_isp_geocodificado (peva_codigo);",
        "CREATE INDEX ON capa2.nodo_isp_geocodificado (es_coordenada_valida);",
        """
        COMMENT ON TABLE capa2.nodo_isp_geocodificado IS
        'Parte A del geoprocesamiento de nodos ISP: latitud/longitud de dbo.NodoISP convertidas de DMS a decimal, validadas contra el bounding box de Ecuador. Sin cruce espacial contra parroquias todavia (Parte B, pendiente shapefile CONALI ORGANIZACION_TERRITORIAL_PARROQUIAL). Ninguna coordenada fuera de rango se corrige automaticamente -- se marca es_coordenada_valida=false con motivo_invalida, para revision, nunca se adivina un valor. EXCEPCION explicita: hemisferio_longitud_inferido=true marca nodos donde la longitud no traia letra de hemisferio y se infirio negativa por ser Ecuador (hecho geografico, no suposicion) -- ver inferir_hemisferio_longitud_faltante().';
        """,
    ]


_SQL_INSERT = text("""
    INSERT INTO capa2.nodo_isp_geocodificado (
        noisp_codigo, peva_codigo, par_codigo, noisp_nombre, tiponodo, estado,
        direccion, verificado_sietel, latitud_original, longitud_original,
        latitud_decimal, longitud_decimal, hemisferio_longitud_inferido,
        es_coordenada_valida, motivo_invalida
    ) VALUES (
        :noisp_codigo, :peva_codigo, :par_codigo, :noisp_nombre, :tiponodo, :estado,
        :direccion, :verificado_sietel, :latitud_original, :longitud_original,
        :latitud_decimal, :longitud_decimal, :hemisferio_longitud_inferido,
        :es_coordenada_valida, :motivo_invalida
    )
""")


def limpiar_coordenadas(dry_run: bool = False) -> None:
    engine = _engine()

    with engine.connect() as conn:
        filas = conn.execute(text("""
            SELECT noisp_codigo, peva_codigo, par_codigo, noisp_nombre,
                   tiponodo, estado, direccion, verificado, latitud, longitud
            FROM analitico.v_nodo_isp_vigente
        """)).mappings().all()

    logger.info("Leídos %s nodos vigentes desde analitico.v_nodo_isp_vigente.", len(filas))

    registros = []
    validas = 0
    hemisferios_inferidos = 0
    motivos_invalidez: dict[str, int] = {}
    for fila in filas:
        lat_dec, motivo_lat = convertir_dms_a_decimal(fila["latitud"])
        lon_dec, motivo_lon = convertir_dms_a_decimal(fila["longitud"])

        lon_dec, se_infirio_hemisferio = inferir_hemisferio_longitud_faltante(fila["longitud"], lon_dec)
        if se_infirio_hemisferio:
            motivo_lon = None  # la conversión original fue exitosa, solo faltaba el signo
            hemisferios_inferidos += 1

        es_valida, motivo_rango = _validar_rango(lat_dec, lon_dec)

        motivo = None
        if es_valida:
            validas += 1
        else:
            partes_motivo = [m for m in (motivo_lat, motivo_lon, motivo_rango) if m]
            motivo = "; ".join(dict.fromkeys(partes_motivo)) if partes_motivo else "invalida_sin_motivo_especifico"
            clave_resumen = motivo_rango or motivo_lat or motivo_lon or "desconocido"
            motivos_invalidez[clave_resumen] = motivos_invalidez.get(clave_resumen, 0) + 1

        registros.append({
            "noisp_codigo": fila["noisp_codigo"],
            "peva_codigo": fila["peva_codigo"],
            "par_codigo": fila["par_codigo"],
            "noisp_nombre": fila["noisp_nombre"],
            "tiponodo": fila["tiponodo"],
            "estado": fila["estado"],
            "direccion": fila["direccion"],
            "verificado_sietel": fila["verificado"],
            "latitud_original": fila["latitud"],
            "longitud_original": fila["longitud"],
            "latitud_decimal": lat_dec if es_valida else None,
            "longitud_decimal": lon_dec if es_valida else None,
            "hemisferio_longitud_inferido": se_infirio_hemisferio,
            "es_coordenada_valida": es_valida,
            "motivo_invalida": motivo,
        })

    total = len(registros)
    logger.info(
        "Procesados %s nodos: %s con coordenada válida (%.1f%%), %s inválida/no convertible.",
        total, validas, 100 * validas / total if total else 0, total - validas,
    )
    if hemisferios_inferidos:
        logger.info(
            "De las válidas, %s tuvieron el hemisferio de longitud inferido "
            "(texto sin letra N/S/E/O/W -- Ecuador es 100%% longitud oeste, no es una suposición).",
            hemisferios_inferidos,
        )
    for motivo_resumen, cantidad in sorted(motivos_invalidez.items(), key=lambda kv: -kv[1]):
        logger.info("  motivo=%s -> %s nodos", motivo_resumen, cantidad)

    if dry_run:
        logger.info("--dry-run: no se escribió nada.")
        return

    with engine.begin() as conn:
        for sentencia in _sentencias_ddl():
            conn.execute(text(sentencia))
        if registros:
            conn.execute(_SQL_INSERT, registros)

    logger.info(
        "capa2.nodo_isp_geocodificado construida: %s filas (%s válidas, %s inválidas).",
        total, validas, total - validas,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo cuenta y clasifica, no escribe capa2.nodo_isp_geocodificado")
    args = parser.parse_args(argv)

    limpiar_coordenadas(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
