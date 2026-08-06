# Shapefile de parroquias — CONALI

Este directorio existe en Git solo como estructura (este `README.md`). Los archivos binarios del
shapefile **nunca se suben por Git** — se transfieren directo a la VM por `scp` (ver abajo), y están
excluidos explícitamente en `.gitignore` (`mart/data/**/*.shp`, `.shx`, `.dbf`, `.prj`, `.cpg`, `.sbn`,
`.sbx`).

## Qué va aquí

`ORGANIZACION_TERRITORIAL_PARROQUIAL.{shp,shx,dbf,prj,cpg}` — límites territoriales a nivel parroquial,
fuente CONALI (Comité Nacional de Límites Internos), corte `17.07.2026`.

Deliberadamente el nivel **parroquial**, no cantonal ni provincial — es el nivel de detalle que se
cruza contra `par_codigo`/`codigo_parroquia` de `dbo.Parroquia`. Los archivos cantonal/provincial de la
misma entrega de CONALI no se usan en este pipeline.

No se usa `SIMBOLOGÍA_DE_LÍMITES_TERRITORIALES/*.lyr` (son archivos de simbología de ArcGIS, no datos
geométricos) ni los `METADATO *.pdf` de la misma carpeta origen — solo el shapefile en sí.

## Esquema de atributos (`.dbf`), confirmado leyendo el archivo real (06-ago-2026)

| Columna      | Tipo | Ejemplo    | Uso                                             |
|--------------|------|------------|--------------------------------------------------|
| `DPA_PARROQ` | C(6) | `010150`   | Código INEC de parroquia — cruce contra `codigo_parroquia` |
| `DPA_DESPAR` | C    | `CUENCA`   | Nombre de parroquia                              |
| `DPA_CANTON` | C(4) | `0101`     | Código INEC de cantón                            |
| `DPA_DESCAN` | C    | `CUENCA`   | Nombre de cantón                                 |
| `DPA_PROVIN` | C(2) | `01`       | Código INEC de provincia                         |
| `DPA_DESPRO` | C    | `AZUAY`    | Nombre de provincia                              |
| `DPA_ANIO`   | C(4) | `2026`     | Año de corte de la información                   |
| `txt`        | C    | `CABECERA CANTONAL` / `PARROQUIA RURAL` | Tipo de parroquia          |
| `fcode`      | C(5) | `HA004`    | Código de feature (uso interno CONALI/IGM)       |

1.052 registros totales (confirmado).

**Importante**: `DPA_PARROQ`/`DPA_CANTON`/`DPA_PROVIN` son códigos INEC directos — el cruce con
`dbo.Parroquia.codigoParroquia` es por código, no por nombre. No hace falta el emparejamiento
aproximado por texto que sí necesitó `samm_pipeline` con su shapefile (más viejo, sin estos códigos
tan explícitos).

## Cómo llega a la VM

Desde la máquina donde tengas el shapefile descargado de CONALI:

```bash
scp ORGANIZACION_TERRITORIAL_PARROQUIAL.shp \
    ORGANIZACION_TERRITORIAL_PARROQUIAL.shx \
    ORGANIZACION_TERRITORIAL_PARROQUIAL.dbf \
    ORGANIZACION_TERRITORIAL_PARROQUIAL.prj \
    ORGANIZACION_TERRITORIAL_PARROQUIAL.cpg \
    root@192.168.129.51:/opt/sietel_pipeline/mart/data/shapefiles/parroquial/
```

Verificar en VM2 tras la copia:

```bash
ls -la /opt/sietel_pipeline/mart/data/shapefiles/parroquial/
```

Deben aparecer los 5 archivos junto a este `README.md`. `mart/detectar_discrepancias_geografia_nodo.py`
(Parte B, pendiente de implementar) lee `ORGANIZACION_TERRITORIAL_PARROQUIAL.shp` desde esta ruta fija.
