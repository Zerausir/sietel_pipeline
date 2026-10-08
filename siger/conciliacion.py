"""
siger/conciliacion.py — Conciliación SIGER ↔ SIETEL/OBTEL por RUC (fase 2,
08-oct-2026): qué coincide en prestador (nombre), RUC y estado de operación.

Lectura (SQL_*, como mart_user) y armado de filas (construir_filas, puro --
ver tests/test_siger_reglas.py). La escritura en
calidad.conciliacion_siger_obtel la hace construir_cruce_obtel.py, en la
misma transacción que los hallazgos.

Universo: RUC de OBTEL (PEVA vigentes, sin "prueba") ∪ RUC con algún título
SAI VIGENTE en SIGER. Un SIGER sin título vigente ni PEVA en OBTEL es
historia, no algo que conciliar.

Reglas (siger/reglas.py, fijadas con siger/perfilar_cruce.py):
  - RUC: SQL_RUC_LIMPIO en ambos lados. Todos los RUC de OBTEL tienen 13
    dígitos, así que no hace falta la regla cédula + '001' del lado de OBTEL.
  - Nombre: similitud_nombre -> nivel_nombre (COINCIDE >= 0,90, PARECIDO
    >= 0,50, DIFIERE).
  - Estado: SIETEL OPERANDO / NO_OPERA / INDETERMINADO
    (estado_operacion_prestador) frente al THESTADO REAL del título SAI de
    referencia en SIGER (VIGENTE si tiene alguno; si no, el de vigencia más
    reciente). Solo VIGENTE cuenta como habilitado.
"""
from collections import Counter, defaultdict
from datetime import datetime

from detectar_conflictos_peva import SQL_RUC_LIMPIO
from reglas import (
    ESTADO_SIGER_HABILITADO,
    categoria_conciliacion,
    coincide_estado,
    estado_operacion_prestador,
    nivel_nombre,
    similitud_nombre,
)


def _rl(col: str) -> str:
    return SQL_RUC_LIMPIO.format(col=col)


# Mismo lado OBTEL que construir_cruce_obtel.SQL_UPSERT_HALLAZGOS: una fila
# por PEVA vigente, sin "prueba", último período primero.
SQL_OBTEL = f"""
SELECT DISTINCT ON (v.peva_codigo)
    v.peva_codigo, v.isp_ruc::text AS isp_ruc, {_rl("v.isp_ruc")} AS ruc_limpio,
    v.isp_nombre, v.isp_tipopersona, v.opera, v.tiene_reportes,
    v.ultimo_anio, v.ultimo_periodo_numero
FROM analitico.v_ultimo_periodo_reportado_detalle v
WHERE v.peva_codigo IS NOT NULL
  AND COALESCE(v.isp_nombre::text, '') NOT ILIKE '%prueba%'
  AND COALESCE(v.nombreComercial::text, '') NOT ILIKE '%prueba%'
ORDER BY v.peva_codigo, v.ultimo_anio DESC NULLS LAST, v.ultimo_periodo_numero DESC NULLS LAST
"""

SQL_SIGER_CONC = f"""
SELECT {_rl("c.ruc_resuelto")} AS ruc_limpio, c.ucp_concnum, c.nombres, c.ruc_origen
FROM siger.v_concesionario_basico c
"""

# Títulos SAI (todos los estados) por RUC del concesionario.
SQL_SIGER_TITULOS = f"""
SELECT DISTINCT {_rl("c.ruc_resuelto")} AS ruc_limpio, t.thsecuencial, t.idsth,
       COALESCE(upper(btrim(t.thestado)), '(NULL)') AS thestado, t.thfechavig
FROM siger.v_titulo_sai t
JOIN siger.v_concesionario_basico c ON c.ucp_concnum = t.ucp_concnum
WHERE c.ruc_resuelto IS NOT NULL
"""


def _unir(valores) -> str | None:
    distintos = sorted({v for v in valores if v})
    return " | ".join(distintos) if distintos else None


def _titulo_referencia(titulos: list[dict]) -> dict | None:
    """El VIGENTE si hay alguno; si no, el de THFECHAVIG más reciente (y
    THSECUENCIAL mayor para desempatar)."""
    if not titulos:
        return None
    return max(titulos, key=lambda t: (t["thestado"] == ESTADO_SIGER_HABILITADO,
                                       t["thfechavig"] or datetime.min, t["thsecuencial"]))


def construir_filas(obtel: list[dict], conc: list[dict], titulos: list[dict]) -> list[dict]:
    obtel_por_ruc, conc_por_ruc, titulos_por_ruc = defaultdict(list), defaultdict(list), defaultdict(list)
    for p in obtel:
        if p["ruc_limpio"]:
            obtel_por_ruc[p["ruc_limpio"]].append(p)
    for c in conc:
        if c["ruc_limpio"]:
            conc_por_ruc[c["ruc_limpio"]].append(c)
    for t in titulos:
        titulos_por_ruc[t["ruc_limpio"]].append(t)

    universo = set(obtel_por_ruc) | {
        r for r, ts in titulos_por_ruc.items() if any(t["thestado"] == ESTADO_SIGER_HABILITADO for t in ts)
    }
    filas = []
    for ruc in sorted(universo):
        pevas, concs, ts = obtel_por_ruc.get(ruc, []), conc_por_ruc.get(ruc, []), titulos_por_ruc.get(ruc, [])
        en_sietel, en_siger = bool(pevas), bool(concs)

        estado_sietel = estado_operacion_prestador([p["opera"] for p in pevas]) if en_sietel else None
        reporta = any(p["tiene_reportes"] for p in pevas) if en_sietel else None
        periodos = [(p["ultimo_anio"], p["ultimo_periodo_numero"]) for p in pevas
                    if p["ultimo_anio"] is not None and p["ultimo_periodo_numero"] is not None]
        ultimo = max(periodos, default=None)

        ref = _titulo_referencia(ts)
        estado_siger = ref["thestado"] if ref else ("SIN_TITULO_SAI" if en_siger else None)

        nombre_sietel = _unir(p["isp_nombre"] for p in pevas)
        nombre_siger = _unir(c["nombres"] for c in concs)
        ambos = en_sietel and en_siger
        sim = similitud_nombre(nombre_sietel, nombre_siger) if ambos else None
        nivel = nivel_nombre(sim)
        ce = coincide_estado(estado_sietel, estado_siger) if ambos else None

        filas.append({
            "ruc_limpio": ruc,
            "categoria": categoria_conciliacion(en_sietel, en_siger, nivel, ce),
            "en_sietel": en_sietel,
            "en_siger": en_siger,
            "nombre_sietel": nombre_sietel,
            "nombre_siger": nombre_siger,
            "similitud_nombre": sim,
            "nivel_nombre": nivel,
            "pevas_sietel": _unir(p["peva_codigo"] for p in pevas),
            "opera_sietel": _unir(p["opera"] or "(NULL)" for p in pevas),
            "estado_sietel": estado_sietel,
            "reporta_sietel": reporta,
            "ultimo_periodo_sietel": f"{ultimo[0]}-{ultimo[1]:02d}" if ultimo else None,
            "ucp_concnums": _unir(c["ucp_concnum"] for c in concs),
            "ruc_por_cedula_001": any(c["ruc_origen"] == "cedula_001" for c in concs),
            "estado_siger": estado_siger,
            "estados_siger": ", ".join(f"{e} ({n})" for e, n in Counter(t["thestado"] for t in ts).most_common())
            or None,
            "idsth_siger": ref["idsth"] if ref else None,
            "vigencia_siger": ref["thfechavig"] if ref else None,
            "titulos_sai": len(ts),
            "coincide_estado": ce,
            "coincide_reporte": (reporta == (estado_siger == ESTADO_SIGER_HABILITADO)) if ambos else None,
        })
    return filas
