"""
siger/perfilar_cruce.py — Perfilamiento de las llaves del cruce SIGER ↔ OBTEL
(fase 1 de la conciliación, 08-oct-2026). SOLO LECTURA, como mart_user.

Antes de construir calidad.conciliacion_siger_obtel hay que fijar con datos
reales tres reglas de coincidencia. Este script mide lo necesario para
decidirlas, sin escribir nada en la base:
  1. RUC:    formato por fuente, RUC de 10 dígitos en OBTEL (¿existen en SIGER
             como cédula + '001'?), origen del RUC en SIGER y repetidos.
  2. Nombre: para los RUC presentes en ambas fuentes, la distribución de la
             similitud (reglas.similitud_nombre) entre isp_nombre de OBTEL y
             nombres de SIGER, con ejemplos por franja: de aquí sale el umbral.
  3. Estado: tabla cruzada por PEVA entre 'opera' de SIETEL (y si reporta) y
             el estado SAI del RUC en SIGER; THESTADO por servicio SAI.

Mismos lados que construir_cruce_obtel.py (misma vista de OBTEL, mismo
filtro de "prueba", una fila por PEVA, SQL_RUC_LIMPIO).

Uso:
    python perfilar_cruce.py                       # informe Markdown por pantalla
    python perfilar_cruce.py --salida /tmp/perfil  # además perfil_cruce.md y
                                                   # pares_nombre.csv (contiene
                                                   # nombres: no compartir fuera
                                                   # del equipo)
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mart"))

from sqlalchemy import text  # noqa: E402

from detectar_conflictos_peva import SQL_RUC_LIMPIO, _engine  # noqa: E402
from reglas import clasificar_opera, similitud_nombre  # noqa: E402


def _rl(col: str) -> str:
    return SQL_RUC_LIMPIO.format(col=col)


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

SQL_SIGER_SAI = f"""
SELECT {_rl("p.ruc_resuelto")} AS ruc_limpio, p.clave_prestador, p.tiene_sai_vigente,
       p.titulos_sai, p.titulos_sai_vigentes, p.ruc_origen
FROM siger.v_prestador_sai p
"""

SQL_THESTADO = """
SELECT t.idsth, t.servicio, COALESCE(btrim(t.thestado), '(NULL)') AS thestado, COUNT(*) AS n
FROM siger.v_titulo_sai t
GROUP BY 1, 2, 3
ORDER BY 1, 4 DESC
"""

FRANJAS = [(1.0, 1.0001, "= 1,00"), (0.9, 1.0, "0,90–0,99"), (0.8, 0.9, "0,80–0,89"),
           (0.7, 0.8, "0,70–0,79"), (0.6, 0.7, "0,60–0,69"), (0.5, 0.6, "0,50–0,59"),
           (0.0, 0.5, "< 0,50")]


def _tabla(encabezados: list[str], filas: list) -> str:
    lineas = ["| " + " | ".join(encabezados) + " |", "|" + "---|" * len(encabezados)]
    lineas += ["| " + " | ".join("" if v is None else (f"{v:,}" if isinstance(v, int) else str(v))
                                 for v in fila) + " |" for fila in filas]
    return "\n".join(lineas)


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f} %" if total else "-"


def _leer() -> dict:
    with _engine().connect() as conn:
        def q(sql):
            return [dict(r) for r in conn.execute(text(sql)).mappings().all()]
        return {"obtel": q(SQL_OBTEL), "conc": q(SQL_SIGER_CONC), "sai": q(SQL_SIGER_SAI),
                "thestado": q(SQL_THESTADO)}


def perfilar(datos: dict) -> tuple[str, list[dict]]:
    obtel, conc, sai = datos["obtel"], datos["conc"], datos["sai"]
    md = ["# Perfilamiento del cruce SIGER ↔ OBTEL", ""]

    # ── Índices por RUC ──
    obtel_por_ruc = defaultdict(list)
    for p in obtel:
        if p["ruc_limpio"]:
            obtel_por_ruc[p["ruc_limpio"]].append(p)
    conc_por_ruc = defaultdict(list)
    for c in conc:
        if c["ruc_limpio"]:
            conc_por_ruc[c["ruc_limpio"]].append(c)
    sai_por_ruc = {s["ruc_limpio"]: s for s in sai if s["ruc_limpio"]}

    def estado_siger(ruc):
        if ruc in sai_por_ruc:
            return "SAI_VIGENTE" if sai_por_ruc[ruc]["tiene_sai_vigente"] else "SAI_NO_VIGENTE"
        return "SIN_TITULO_SAI" if ruc in conc_por_ruc else "NO_EXISTE_EN_SIGER"

    # ── 0. Universos ──
    rucs_sai_vig = {r for r, s in sai_por_ruc.items() if s["tiene_sai_vigente"]}
    rucs_obtel = set(obtel_por_ruc)
    md += ["## 0. Universos", "", _tabla(["Conjunto", "Cantidad"], [
        ("PEVA vigentes en OBTEL (sin 'prueba')", len(obtel)),
        ("  … sin RUC", sum(1 for p in obtel if not p["ruc_limpio"])),
        ("RUC distintos en OBTEL", len(rucs_obtel)),
        ("Concesionarios en SIGER", len(conc)),
        ("Prestadores SAI en SIGER (cualquier estado)", len(sai)),
        ("  … sin RUC resuelto", sum(1 for s in sai if not s["ruc_limpio"])),
        ("RUC con SAI vigente en SIGER", len(rucs_sai_vig)),
        ("RUC en OBTEL y con SAI vigente en SIGER", len(rucs_obtel & rucs_sai_vig)),
        ("RUC en OBTEL y en algún concesionario de SIGER", len(rucs_obtel & set(conc_por_ruc))),
    ]), ""]

    # ── 1. RUC ──
    long_obtel = Counter(len(p["ruc_limpio"]) if p["ruc_limpio"] else 0 for p in obtel)
    con_no_digitos = sum(1 for p in obtel if p["isp_ruc"] and p["ruc_limpio"]
                         and p["isp_ruc"].strip() != p["ruc_limpio"])
    diez = sorted({p["ruc_limpio"] for p in obtel if p["ruc_limpio"] and len(p["ruc_limpio"]) == 10})
    diez_en_siger = [r for r in diez if r + "001" in conc_por_ruc]
    origen_sai = Counter(s["ruc_origen"] for s in sai)
    md += ["## 1. RUC", "", "**Longitud de `ruc_limpio` en OBTEL (por PEVA)**", "",
           _tabla(["Dígitos", "PEVA"], [(k if k else "sin RUC", v) for k, v in sorted(long_obtel.items())]), "",
           f"- PEVA cuyo `isp_ruc` traía caracteres no numéricos (se limpian): {con_no_digitos:,}",
           f"- RUC de 10 dígitos en OBTEL: {len(diez):,}; de ellos, existen en SIGER como cédula + '001': "
           f"{len(diez_en_siger):,}. **Si son muchos, la conciliación debe aplicar la misma regla a OBTEL.**",
           f"- RUC de OBTEL con más de un PEVA: {sum(1 for v in obtel_por_ruc.values() if len(v) > 1):,}",
           f"- RUC de SIGER con más de un concesionario (`ucp_concnum`): "
           f"{sum(1 for v in conc_por_ruc.values() if len(v) > 1):,}", "",
           "**Origen del RUC en prestadores SAI de SIGER**", "",
           _tabla(["ruc_origen", "Prestadores"], sorted(origen_sai.items(), key=lambda x: -x[1])), ""]

    # ── 2. Nombre ──
    pares = []
    for ruc in sorted(rucs_obtel & set(conc_por_ruc)):
        n_obtel = " | ".join(sorted({p["isp_nombre"] for p in obtel_por_ruc[ruc] if p["isp_nombre"]}))
        n_siger = " | ".join(sorted({c["nombres"] for c in conc_por_ruc[ruc] if c["nombres"]}))
        pares.append({"ruc_limpio": ruc, "nombre_obtel": n_obtel, "nombre_siger": n_siger,
                      "similitud": similitud_nombre(n_obtel, n_siger), "estado_siger": estado_siger(ruc),
                      "por_cedula_001": any(c["ruc_origen"] == "cedula_001" for c in conc_por_ruc[ruc])})
    filas_franja, ejemplos = [], []
    for lo, hi, etiqueta in FRANJAS:
        en = [p for p in pares if lo <= p["similitud"] < hi]
        filas_franja.append((etiqueta, len(en), _pct(len(en), len(pares)),
                             sum(1 for p in en if p["por_cedula_001"])))
        if lo < 1.0:
            ejemplos += [(etiqueta, p["similitud"], p["nombre_obtel"], p["nombre_siger"]) for p in en[:5]]
    md += ["## 2. Nombre (RUC presentes en ambas fuentes)", "",
           f"{len(pares):,} RUC comparados. Similitud con `reglas.similitud_nombre` sobre nombres normalizados.", "",
           _tabla(["Similitud", "RUC", "%", "De ellos por cédula+001"], filas_franja), "",
           "**Ejemplos por franja (hasta 5)**: para elegir el umbral de 'coincide'.", "",
           _tabla(["Franja", "Sim.", "OBTEL", "SIGER"], ejemplos), ""]

    # ── 3. Estado ──
    cruz_opera = Counter()
    cruz_reporta = Counter()
    for p in obtel:
        es = estado_siger(p["ruc_limpio"]) if p["ruc_limpio"] else "SIN_RUC_EN_OBTEL"
        cruz_opera[(p["opera"] or "(NULL)", clasificar_opera(p["opera"]), es)] += 1
        cruz_reporta[("sí" if p["tiene_reportes"] else "no", es)] += 1
    estados = ["SAI_VIGENTE", "SAI_NO_VIGENTE", "SIN_TITULO_SAI", "NO_EXISTE_EN_SIGER", "SIN_RUC_EN_OBTEL"]
    claves_opera = sorted({(o, c) for o, c, _ in cruz_opera}, key=lambda k: (k[1], k[0]))
    md += ["## 3. Estado", "", "**PEVA de OBTEL: `opera` (SIETEL) × estado SAI del RUC en SIGER**", "",
           _tabla(["opera", "Clase", *estados],
                  [(o, c, *[cruz_opera[(o, c, e)] for e in estados]) for o, c in claves_opera]), "",
           "**PEVA de OBTEL: ¿reporta? × estado SAI en SIGER**", "",
           _tabla(["Reporta", *estados], [(r, *[cruz_reporta[(r, e)] for e in estados]) for r in ("sí", "no")]), "",
           "**THESTADO de los títulos SAI en SIGER**", "",
           _tabla(["IDSTH", "Servicio", "THESTADO", "Títulos"],
                  [(t["idsth"], t["servicio"], t["thestado"], int(t["n"])) for t in datos["thestado"]]), ""]
    return "\n".join(md), pares


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--salida", type=Path, help="Carpeta donde guardar perfil_cruce.md y pares_nombre.csv")
    args = parser.parse_args(argv)
    informe, pares = perfilar(_leer())
    print(informe)
    if args.salida:
        args.salida.mkdir(parents=True, exist_ok=True)
        (args.salida / "perfil_cruce.md").write_text(informe, encoding="utf-8")
        with open(args.salida / "pares_nombre.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(pares[0]) if pares else ["ruc_limpio"])
            w.writeheader()
            w.writerows(sorted(pares, key=lambda p: p["similitud"]))
        print(f"\nGuardado en {args.salida}/perfil_cruce.md y pares_nombre.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
