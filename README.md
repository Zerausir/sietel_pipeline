# OBTEL — Observatorio de Telecomunicaciones

Sistema de datos de extremo a extremo para dos módulos de **SIETEL** (el sistema regulatorio de ARCOTEL sobre SQL
Server): **Líneas Dedicadas de Internet Fijo** y **Geografía de Nodos ISP**. Extrae, certifica, modela y expone en un
dashboard analítico propio la información que los prestadores de servicios de telecomunicaciones reportan al regulador —
como insumo tanto para el análisis de mercado como para el control y la regulación del sector.

Desarrollado por la **Dirección de Mercados — ARCOTEL**.

## Versiones del software

**Orquestación e infraestructura**

[![Apache Airflow](https://img.shields.io/badge/Apache%20Airflow-3.3.0-017CEE?logo=apacheairflow&logoColor=white)](https://airflow.apache.org/)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![ODBC Driver](https://img.shields.io/badge/ODBC%20Driver%20for%20SQL%20Server-18-CC2927?logo=microsoftsqlserver&logoColor=white)](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
[![Docker Compose](https://img.shields.io/badge/Docker%20Compose-v2-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

**Capa 1** — `requirements.txt` (raíz)

[![pyodbc](https://img.shields.io/badge/pyodbc-5.3.0-4B8BBE)](https://pypi.org/project/pyodbc/)
[![psycopg2-binary](https://img.shields.io/badge/psycopg2--binary-2.9.12-336791?logo=postgresql&logoColor=white)](https://pypi.org/project/psycopg2-binary/)
[![python-dotenv](https://img.shields.io/badge/python--dotenv-1.2.2-ECD53F)](https://pypi.org/project/python-dotenv/)

**Capa 2/3** — `mart/requirements.txt`

[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0.51-D71F00)](https://www.sqlalchemy.org/)
[![psycopg](https://img.shields.io/badge/psycopg%5Bbinary%5D-3.3.4-336791?logo=postgresql&logoColor=white)](https://www.psycopg.org/psycopg3/)
[![python-dotenv](https://img.shields.io/badge/python--dotenv-1.2.2-ECD53F)](https://pypi.org/project/python-dotenv/)
[![geopandas](https://img.shields.io/badge/geopandas-1.1.4-139C5A)](https://geopandas.org/)

> `shapely` **no** está pinneado explícitamente en `mart/requirements.txt` — llega como dependencia transitiva de
> `geopandas`. Se usa directamente (`shapely.geometry`, `shapely.strtree.STRtree`) en
> `mart/detectar_discrepancias_geografia_nodo.py`. `geopandas` en sí se usa **solo** en `mart/cargar_parroquias.py`
> (lectura del shapefile CONALI, una sola vez) — el resto de `mart/` nunca lo importa.

**Dashboard** — `dashboard/requirements.txt`

[![Dash](https://img.shields.io/badge/Dash-4.4.1-008DE4?logo=plotly&logoColor=white)](https://dash.plotly.com/)
[![dash-ag-grid](https://img.shields.io/badge/dash--ag--grid-35.3.0-1D1D1D)](https://github.com/plotly/dash-ag-grid)
[![dash-mantine-components](https://img.shields.io/badge/dash--mantine--components-2.8.0-339AF0)](https://www.dash-mantine-components.com/)
[![openpyxl](https://img.shields.io/badge/openpyxl-3.1.5-217346?logo=microsoftexcel&logoColor=white)](https://openpyxl.readthedocs.io/)
[![pandas](https://img.shields.io/badge/pandas-3.0.5-150458?logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0.51-D71F00)](https://www.sqlalchemy.org/)
[![psycopg](https://img.shields.io/badge/psycopg%5Bbinary%5D-3.3.4-336791?logo=postgresql&logoColor=white)](https://www.psycopg.org/psycopg3/)
[![python-dotenv](https://img.shields.io/badge/python--dotenv-1.2.2-ECD53F)](https://pypi.org/project/python-dotenv/)
[![Flask-Caching](https://img.shields.io/badge/Flask--Caching-2.4.1-000000?logo=flask&logoColor=white)](https://flask-caching.readthedocs.io/)
[![Flask-Login](https://img.shields.io/badge/Flask--Login-0.6.3-000000?logo=flask&logoColor=white)](https://flask-login.readthedocs.io/)
[![bcrypt](https://img.shields.io/badge/bcrypt-5.0.0-4B8BBE)](https://pypi.org/project/bcrypt/)
[![gunicorn](https://img.shields.io/badge/gunicorn-26.0.0-499848?logo=gunicorn&logoColor=white)](https://gunicorn.org/)

> El dashboard **no** usa `geopandas`/`shapely` — el polígono del mapa de nodos se sirve ya precalculado desde
> `mart.vw_geometria_territorio_nodo` (ver [Geografía de nodos ISP](#geografía-de-nodos-isp)). `dash-mantine-components`
> se agregó en agosto de 2026 exclusivamente para dos widgets que `dcc`/`dash-ag-grid` no resuelven bien:
> `dmc.MonthPickerInput` (selectores de período, calendario de meses sin nivel de día) y `dmc.NumberInput` (steppers
> numéricos — reemplazó a `dcc.Input(type="number")`, cuyo spinner nativo perdía el valor del recuadro al usar las
> flechas +/-, ver [Historial de correcciones](#historial-de-correcciones)). Requiere fijar
> `_dash_renderer._set_react_version("18.2.0")` **antes** de instanciar `Dash()` — ver `dashboard/app.py`.

---

## Tabla de contenidos

- [Qué hace este proyecto](#qué-hace-este-proyecto)
- [Por qué existe](#por-qué-existe)
- [Arquitectura general](#arquitectura-general)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Las tres capas, en detalle — Líneas Dedicadas](#las-tres-capas-en-detalle--líneas-dedicadas)
- [Principio metodológico: nunca imputar para medir concentración de mercado](#principio-metodológico-nunca-imputar-para-medir-concentración-de-mercado)
- [Geografía de nodos ISP](#geografía-de-nodos-isp)
- [El dashboard, módulo por módulo](#el-dashboard-módulo-por-módulo)
- [Requisitos previos](#requisitos-previos)
- [Roles y permisos de PostgreSQL](#roles-y-permisos-de-postgresql)
- [Configuración](#configuración)
- [Puesta en marcha, paso a paso](#puesta-en-marcha-paso-a-paso)
- [Uso diario](#uso-diario)
- [Modelo de datos](#modelo-de-datos)
- [Códigos administrativos y sincronización](#códigos-administrativos-y-sincronización)
- [Historial de correcciones](#historial-de-correcciones)
- [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)
- [Validación y certificación de datos](#validación-y-certificación-de-datos)
- [Calidad de datos conocida](#calidad-de-datos-conocida)
- [Seguridad del dashboard](#seguridad-del-dashboard)
- [Pruebas de integración](#pruebas-de-integración)
- [Documentación relacionada](#documentación-relacionada)
- [Hoja de ruta / pendientes](#hoja-de-ruta--pendientes)
- [Dónde obtener ayuda](#dónde-obtener-ayuda)
- [Mantenedores](#mantenedores)

---

## Qué hace este proyecto

**Líneas Dedicadas de Internet Fijo:**

- Extrae y **agrega en el propio SQL Server** (nunca transfiere el detalle crudo) los datos de
  `dbo.VALineasDedicadas` — la tabla de origen verdaderamente auditable, reportada mes a mes por cada prestador.
- Certifica cada carga con un **hash MD5 recalculado desde el origen**: no solo verifica que la cantidad de filas
  coincida, verifica que el **valor** de cada fila coincida.
- Versiona las dimensiones `ISP` y `PermisoVAgregado` con **SCD Tipo 2**, para poder resolver el estado de un prestador
  en cualquier punto del histórico, aunque SIETEL solo exponga su estado *actual*.
- Detecta y clasifica automáticamente **RUC con múltiples PEVA en conflicto**, con un flujo de revisión humana
  persistente para los casos que no se pueden resolver solos.
- Reconstruye una **serie mensual completa** para cada PEVA, rellenando huecos **solo hacia el interior** (nunca
  extrapola hacia adelante) y marcando de forma explícita, fila por fila, qué es un reporte real y qué es relleno.
- Calcula **IHH, CR2, CR4 y participación de mercado exclusivamente sobre datos reportados** — nunca sobre datos
  imputados —, publicando siempre un indicador de cobertura junto al índice.

**Geografía de nodos ISP** (agregado ago-2026):

- Extrae `dbo.NodoISP` (nodos de acceso físico de cada prestador) con el mismo criterio SCD Tipo 2 que
  ISP/PermisoVAgregado.
- Limpia coordenadas capturadas en texto libre (formato DMS inconsistente) a decimal, sin corregir nunca a ciegas — solo
  aplica una inferencia de hemisferio de longitud basada en un hecho geográfico verificable (Ecuador es 100% longitud
  oeste), nunca a latitud.
- Cruza cada nodo, por coordenada, contra el shapefile oficial de parroquias de **CONALI** (punto-en-polígono, sin
  PostGIS) para obtener su geografía real, y la compara contra lo reportado en SIETEL — **CONALI se trata como fuente
  autoritativa**, por tener una codificación INEC más reciente que la tabla `dbo.Parroquia` de SIETEL.
- Publica **dos vistas del dashboard**: nodos sin discrepancia (mapa nacional, coloreado por tipo de nodo) y nodos con
  discrepancia de cantón (solo lectura — la revisión formal ocurre fuera de OBTEL).

**Control** (agregado ago-2026) — módulo de inconsistencias para seguimiento regulatorio, sin datos ni modelo nuevo en
`mart`: reutiliza vistas ya existentes (`vw_prestadores_sin_reportar`, `vw_prestadores_reporte_detenido`) más una
consulta nueva de variación mensual anómala (ventana `LAG()` sobre `fact_lineas_geografia_mes`), todo resuelto en la
capa de consultas del dashboard, no en PostgreSQL.

**Ambos módulos comparten:**

- Un **dashboard web** (Dash + PostgreSQL) con autenticación propia — OBTEL — para que la Dirección de Mercados analice
  evolución del mercado, cumplimiento de reporte, concentración, geografía de infraestructura y control regulatorio, sin
  depender de Power BI para el día a día.

## Por qué existe

`dbo.VAReporteUsuariosCuentas` (la tabla que en teoría ya resume la información de líneas dedicadas) fue descartada como
fuente: es una tabla física sin ningún proceso de cálculo auditable en el esquema de SIETEL — sin vista, trigger ni
procedimiento almacenado que explique cómo se puebla —, por lo que sus inconsistencias no son trazables al origen. Ese
hallazgo está documentado formalmente en `Informe_Hallazgos_SIETEL.docx`.

`dbo.VALineasDedicadas` sí es un dato crudo auditable: una fila por línea dedicada, por cliente, por período, reportada
directamente por el prestador. El módulo de geografía de nodos nació de una necesidad distinta: **SIETEL no tiene forma
propia de verificar si la ubicación reportada de un nodo es correcta** — `dbo.Parroquia` usa una codificación
administrativa vieja, y nadie la había cruzado nunca contra una fuente cartográfica independiente hasta este proyecto.
El módulo Control nació de una tercera necesidad: ninguna de las dos vistas anteriores reunía en un solo lugar las
inconsistencias que importan para *control regulatorio* específicamente (quién nunca reportó, quién dejó de hacerlo,
quién cambió drásticamente lo que reporta) — existían como piezas sueltas (un KPI aislado, una vista nunca expuesta) en
vez de un módulo dedicado con sus propios filtros y gráficos.

## Arquitectura general

```
[SQL Server SIETEL — VALineasDedicadas, ISP, PermisoVAgregado, NodoISP, Parroquia, Ciudad, Provincia]
        │  pyodbc + ODBC Driver 18 for SQL Server
        │  Fix OpenSSL UnsafeLegacyRenegotiation (SQL Server 2008 R2 no soporta RFC 5746)
        ▼
┌───────────────────────────── CAPA 1 ─────────────────────────────┐
│ DAG: sietel_usuarios_cuentas_pipeline                             │
│ esquema → dimensiones SCD Tipo 2 (ISP, PermisoVAgregado) →        │
│ nodos ISP (SCD Tipo 2 + códigos INEC) →                           │
│ años → hechos (mapeado) → validación cruzada certificada (hash)   │
│ Destino: PostgreSQL, esquemas staging (tablas) y analitico (vistas)│
└────────────────────────────────────────────────────────────────────┘
        ▼
┌───────────────────────────── CAPA 2/3 ────────────────────────────┐
│ DAG: sietel_mart_pipeline                                         │
│ 1) detectar_conflictos_peva      → esquema calidad                │
│ 2) construir_capa2               → capa2.lineas_dedicadas_consolidado│
│ 3) limpiar_coordenadas_nodo_isp  → capa2.nodo_isp_geocodificado   │
│ 4) cargar_parroquias             → capa2.parroquias_geometria +   │
│                                     capa2.territorio_geometria_nodo│
│ 5) detectar_discrepancias_geografia_nodo → calidad + capa2        │
│ 6) aplicar_capa3                 → esquema mart (sql/02_ddl_mart.sql)│
└────────────────────────────────────────────────────────────────────┘
        ▼
┌───────────────────────────── DASHBOARD ───────────────────────────┐
│ Dash + Flask-Login + gunicorn, contenedor propio                  │
│ Evolución · IHH y participación · Mapa de nodos ·                 │
│ Discrepancias de geografía · Control                              │
│ Lee exclusivamente mart.* (rol de solo lectura dashboard_lector)  │
└────────────────────────────────────────────────────────────────────┘
        ▼
Power BI (reportes existentes, Líneas Dedicadas) + Dashboard propio (uso diario, Dirección de Mercados)
```

**Por qué `pyodbc` y no `pymssql`:** el servidor SIETEL exige una negociación TLS que FreeTDS (usado internamente por
`pymssql`) rechaza durante el handshake — confirmado con TDSDUMP, error "login packet rejected". El driver ODBC oficial
de Microsoft sí negocia correctamente.

**Por qué el fix de OpenSSL:** SQL Server 2008 R2 no soporta RFC 5746 (renegociación TLS segura), que OpenSSL 3.x exige
por defecto. El fix se aplica solo dentro del contenedor de `docker/Dockerfile` — no debe extenderse nunca a un
contenedor compartido con otro pipeline.

**Por qué `capa2` son tablas físicas reconstruidas, no vistas:** tanto el relleno LOCF interior de líneas dedicadas como
el cruce punto-en-polígono de nodos requieren procesamiento (ventanas ordenadas, `shapely`) que sería inviable
recalcular en cada consulta del dashboard. Se reconstruyen por completo en cada corrida de `sietel_mart_pipeline`.

**Por qué el geoprocesamiento de nodos no usa PostGIS:** este proyecto corre sobre una instancia PostgreSQL estándar sin
extensiones geoespaciales instaladas. El cruce punto-en-polígono se resuelve con `shapely` + `STRtree` en Python, contra
geometría almacenada como GeoJSON en columnas `JSONB` — mismo patrón que
[`Zerausir/samm_pipeline`](https://github.com/Zerausir/samm_pipeline).

**Por qué Control no agrega tablas/vistas nuevas a `mart`:** dos de sus tres secciones reutilizan vistas que ya existían
(`vw_prestadores_sin_reportar`, `vw_prestadores_reporte_detenido`); la tercera (variación mensual anómala) es una
agregación con ventana (`LAG()`) sobre `fact_lineas_geografia_mes`, calculada al vuelo en
`dashboard/services/queries.py` — no justificaba una vista materializada nueva ni un cambio de esquema.

## Estructura del repositorio

```
sietel_pipeline/
├── dags/
│   ├── sietel_usuarios_cuentas_pipeline.py   # Capa 1: SQL Server → staging/analitico
│   └── sietel_mart_pipeline.py               # Capa 2/3: conflictos PEVA → capa2 → geografía nodos → mart
├── scripts/                                  # Capa 1
│   ├── config.py                             # Conexiones, ANIO_INICIO_HISTORICO=2011 / ANIO_FIN_HISTORICO=2025
│   ├── aplicar_esquema.py                    # Ejecuta sql/01_ddl_postgres.sql de forma idempotente
│   ├── cargar_dimensiones.py                 # SCD Tipo 2: dim_isp y dim_permiso_va_agregado
│   ├── cargar_nodo_isp.py                    # SCD Tipo 2: dim_nodo_isp (NodoISP + códigos INEC)
│   ├── cargar_hechos_anio.py                 # Extracción agregada mes a mes + upsert certificado por hash
│   ├── sincronizar_codigos_administrativos.py# Backfill idempotente de códigos INEC, standalone (fuera del DAG)
│   ├── validar_carga.py                      # Certificación cruzada SQL Server vs PostgreSQL
│   └── remediar_versiones_espurias_scd2.py   # Remediación puntual de versiones SCD2 espurias (ver Historial)
├── mart/                                     # Capa 2/3
│   ├── detectar_conflictos_peva.py           # Detecta/clasifica RUC con múltiples PEVA, resuelve Grupo A
│   ├── construir_capa2.py                    # Reconstruye capa2.lineas_dedicadas_consolidado (LOCF interior)
│   ├── limpiar_coordenadas_nodo_isp.py       # Parte A geografía de nodos: DMS -> decimal, validación de rango
│   ├── cargar_parroquias.py                  # Carga shapefile CONALI (idempotente) + geometría precalculada
│   ├── detectar_discrepancias_geografia_nodo.py # Parte B: cruce punto-en-polígono, discrepancias por cantón
│   ├── aplicar_capa3.py                      # Aplica sql/02_ddl_mart.sql completo (protocolo simple de Postgres)
│   ├── data/shapefiles/parroquial/           # Shapefile CONALI -- NUNCA en Git, ver README propio de la carpeta
│   └── requirements.txt
├── sql/
│   ├── 00_roles_mart.sql                     # Permisos de mart_user (dueño de capa2/mart/calidad)
│   ├── 01_ddl_postgres.sql                   # DDL Capa 1: tablas, índices, dimensiones (ISP, Permiso, NodoISP), vistas
│   ├── 02_ddl_mart.sql                       # DDL Capa 3: esquema mart completo (líneas + geografía de nodos)
│   ├── 03_ddl_auth.sql                       # Esquema auth: login del dashboard (Flask-Login + bcrypt)
│   ├── 04_ddl_calidad.sql                    # Esquema calidad: conflictos RUC/PEVA + discrepancias de nodo
│   ├── 05_roles_eda.sql                      # Permisos del rol de solo lectura eda_lector (EDA/ML exploratorio)
│   ├── 06_patch_vw_prestadores_sin_reportar.sql     # Parche puntual, ver Historial de correcciones
│   ├── 07_patch_vw_prestadores_reporte_detenido.sql # Parche puntual, ver Historial de correcciones
│   └── 08_patch_fact_ihh_geografico.sql             # Parche puntual, ver Historial de correcciones
├── dashboard/                                 # Aplicación Dash
│   ├── app.py                                # Layout raíz, stores compartidos, navegación, MantineProvider
│   ├── auth.py                                # Flask-Login + bcrypt, blueprint /login /logout
│   ├── config.py                              # Settings (dataclass), variables de entorno del dashboard
│   ├── extensions.py                          # Instancia compartida de Flask-Caching
│   ├── requirements.txt
│   ├── .env.example
│   ├── assets/styles.css                     # Tema visual (variables CSS, tarjetas KPI, grids de filtros)
│   ├── components/
│   │   ├── ui.py                              # Helpers de UI: kpi_card, chart_card, month_year_picker,
│   │   │                                      #   numeric_stepper, excel_download_button, filters_summary_bar,
│   │   │                                      #   compute_mapbox_view, mapbox_polygon_layers
│   │   ├── territory_filters.py               # Nivel/Provincia/Cantón/Parroquia, selección única -- Evolución/Concentración
│   │   ├── node_territory_filters.py          # Provincia/Cantón/Parroquia, sin Nivel, multi-select -- geografía de NODOS
│   │   ├── lines_territory_filters.py         # Provincia/Cantón/Parroquia, sin Nivel, multi-select -- geografía de LÍNEAS (Control)
│   │   └── filters_shared.py                  # Filtro de Estado de operación / Prestador, sincronizado
│   ├── pages/
│   │   ├── inicio.py                          # Panel de opciones (selector de módulos), path "/"
│   │   ├── evolucion.py                       # "Evolución" (líneas dedicadas)
│   │   ├── concentracion.py                   # "IHH y participación" (líneas dedicadas)
│   │   ├── mapa_nodos.py                      # "Mapa de nodos" (sin discrepancia de geografía)
│   │   ├── discrepancias_geografia.py         # "Discrepancias de geografía" (solo lectura)
│   │   └── control.py                         # "Control" (inconsistencias de reporte)
│   ├── services/
│   │   ├── database.py                        # Engines SQLAlchemy (mart_lector, auth) + validadores de esquema
│   │   └── queries.py                         # Todas las consultas cacheadas contra mart.*
│   ├── scripts/gestionar_usuarios.py          # CLI administrativo: alta/baja/reset de usuarios del dashboard
│   ├── templates/login.html                   # Página de login (Flask puro, no una página de Dash)
│   └── docker/{Dockerfile,docker-compose.yml}
├── docker/{Dockerfile,docker-compose.yml}     # Contenedor de Airflow (Capas 1 y 2/3)
├── tests/verificar_pipeline.py                # Pruebas de integración end-to-end contra el entorno real (Capa 1)
├── requirements.txt                            # Para ejecutar scripts/ localmente, fuera de Docker
└── .gitignore
```

> **Nota:** no existe `docker/requirements.txt` ni `.env.example` en la raíz — las dependencias del contenedor de
> Airflow se instalan directamente en `docker/Dockerfile`. `dashboard/` y `mart/` sí tienen su propio
> `requirements.txt`.
>
> **`mart/data/shapefiles/parroquial/`** contiene solo un `README.md` en Git — los archivos binarios del shapefile
> (`.shp`/`.shx`/`.dbf`/`.prj`/`.cpg`/`.sbn`/`.sbx`, ~223 MB) se transfieren por `scp` directo a cada VM, nunca por
> Git. Ver el `README.md` de esa carpeta para el esquema de atributos del shapefile y el comando exacto de
> transferencia.

## Las tres capas, en detalle — Líneas Dedicadas

### Capa 1 — Pipeline SIETEL → PostgreSQL (`staging` / `analitico`)

Orquestada por el DAG **`sietel_usuarios_cuentas_pipeline`** (`schedule=None`, disparo manual):

```
aplicar_esquema >> cargar_dimensiones >> cargar_nodos_isp >> obtener_anios_a_cargar
                                              >> cargar_hechos_de_anio.expand(anio=anios)
                                                     >> validar_carga(anios)
```

- **`aplicar_esquema`** ejecuta `sql/01_ddl_postgres.sql` de forma idempotente.
- **`cargar_dimensiones`** versiona `dim_isp` y `dim_permiso_va_agregado` con SCD Tipo 2. Las columnas que disparan una
  nueva versión (`COLUMNAS_VERSIONABLES_ISP`, `COLUMNAS_VERSIONABLES_PERMISO`) son una **propuesta inicial pendiente de
  confirmar formalmente con el área de Mercados**.
- **`cargar_nodos_isp`** versiona `dim_nodo_isp` (`dbo.NodoISP`) con el mismo criterio SCD Tipo 2, incluidos los códigos
  INEC de parroquia/cantón/provincia del nodo (vía `JOIN` contra `dbo.Parroquia`/`Ciudad`/`Provincia`). **
  `dbo.NodoISP_Auxiliar` se excluye deliberadamente** — confirmado con un EDA dirigido que está congelada desde 2014 y
  no tiene ningún PEVA exclusivo que no esté ya en `NodoISP`.
- **`obtener_anios_a_cargar`** lee la Variable de Airflow `sietel_anios_a_cargar`.
- **`cargar_hechos_de_anio`** extrae `dbo.VALineasDedicadas` agregado, particionado mes a mes, certificado con hash MD5
  antes del `UPSERT`.
- **`validar_carga`** recalcula el mismo agregado desde SQL Server, mes a mes, y compara hash MD5 fila por fila.

### Capa 2 — Consolidación y calidad (`capa2` / `calidad`)

Seis tareas del DAG **`sietel_mart_pipeline`**:

1. **`detectar_conflictos_peva`** (`mart/detectar_conflictos_peva.py`) — identifica RUC con múltiples `peva_codigo`
   y los clasifica en tres categorías, persistidas en `calidad.conflictos_ruc_peva`:
    - **A — Duplicado por codificación heredada**: resolución automática.
    - **B — Secuencia del mismo titular**: revisión manual.
    - **C — Nombres distintos bajo el mismo RUC**: siempre revisión manual.

   Las columnas de *workflow* (`estado_revision`, `revisado_por`, etc.) se fijan una sola vez y **nunca se
   sobreescriben** en corridas posteriores.

2. **`construir_capa2`** (`mart/construir_capa2.py`) — reconstruye por completo
   `capa2.lineas_dedicadas_consolidado`, con relleno **LOCF exclusivamente hacia el interior** de la serie de cada PEVA.
3. **`limpiar_coordenadas_nodo_isp`** — ver [Geografía de nodos ISP](#geografía-de-nodos-isp).
4. **`cargar_parroquias`** — ver [Geografía de nodos ISP](#geografía-de-nodos-isp).
5. **`detectar_discrepancias_geografia_nodo`** — ver [Geografía de nodos ISP](#geografía-de-nodos-isp).

### Capa 3 — Mart analítico (`mart`)

Última tarea del DAG: **`aplicar_capa3`** (`mart/aplicar_capa3.py`) aplica `sql/02_ddl_mart.sql` completo contra
PostgreSQL, como `mart_user`, vía el **protocolo simple** de Postgres (conexión `psycopg` cruda en
`autocommit=True`) — necesario porque el archivo trae su propio `BEGIN;`/`COMMIT;`.

El archivo, en orden: `DROP SCHEMA mart CASCADE` + `CREATE SCHEMA` (mart es **completamente reconstruible** en cada
corrida) → dimensiones y puentes → hechos de líneas dedicadas → dimensiones y vistas de geografía de nodos → vistas
`vw_dashboard_*` → **re-otorgamiento explícito de permisos** a `dashboard_lector`/`calidad_lector`/`eda_lector` (el
`DROP SCHEMA CASCADE` inicial borra cualquier `GRANT` previo) → validaciones de integridad (fuera de la transacción).

**Principio de diseño explícito en todo el archivo**: el cálculo de líneas reportadas, participación de mercado e IHH
usa **exclusivamente `lineas_reportadas`** — nunca `total_lineas`. Ver la sección siguiente.

## Principio metodológico: nunca imputar para medir concentración de mercado

Este es el criterio de diseño más importante de todo el sistema, y vale la pena explicarlo una vez, completo:

**El relleno de huecos (LOCF) es aceptable para continuidad visual de una serie de tiempo, pero nunca para medir la
estructura competitiva de un mercado en un mes específico.** Un prestador que deja de reportar tiene una probabilidad
desproporcionadamente alta de estar en crisis, saliendo del mercado, o en incumplimiento — es un caso clásico de dato
faltante *no aleatorio* (MNAR). Heredar su último valor conocido asume implícitamente "sin cambios", cuando
estadísticamente es más probable lo contrario.

Por eso:

- **`fact_lineas_geografia_mes.tiene_reportado`** distingue, para cada prestador y mes, si hubo un reporte real ese mes
  exacto — independientemente de si `capa2` tiene un valor (real o heredado) para ese mes.
- **`fact_participacion_mercado`** calcula `participacion_porcentaje` / `aporte_ihh` **solo** con
  `lineas_reportadas` de quienes tienen `tiene_reportado = TRUE` ese mes. Nunca en `0%` ni con su último valor conocido.
- **`fact_ihh_geografico`** expone columnas de **cobertura** junto al índice, y una alerta adicional de **prestador
  dominante ausente**: un prestador que en algún período de su historia alcanzó ≥30% de participación real en un
  territorio, y no reportó ese mes. **Acotada estrictamente a nivel NACIONAL** — se intentó extender a provincia y se
  descubrió que prestadores chicos superan el 30% en provincias con pocos competidores y quedan marcados "ausentes"
  para siempre tras salir del mercado.
- **La obligación de reportar de un prestador empieza un año calendario después de la fecha del título habilitante**, no
  el día del otorgamiento. `get_reporting_summary` (dashboard) y `vw_prestadores_sin_reportar`
  (`fuera_de_gracia`) aplican esta regla.
- **Límite reconocido explícitamente**: un prestador que **jamás** ha entregado un solo reporte no aparece en
  `capa2` ni en `fact_lineas_geografia_mes`. Se hace visible aparte vía `mart.vw_prestadores_sin_reportar`
  (clasificado en `activo_sin_reportar` / `no_operativo` / `zona_gris`), solo a nivel Nacional — **este límite se
  mantiene igual en Control**: los filtros de Provincia/Cantón/Parroquia no pueden aplicarse a esa tabla, porque la
  fuente misma no tiene la columna.
- **`mart.vw_prestadores_reporte_detenido`** — complemento del anterior: prestadores que sí reportaron al menos una vez
  y luego se detuvieron, usando un período de referencia con margen de 3 meses (no el último período crudo) para no
  marcar como "detenido" un rezago normal de carga.
- **`services/queries.py:get_variacion_mensual_anomala`** (Control, dashboard) extiende el mismo principio a un caso
  nuevo: comparar cuántas cuentas reporta un prestador mes a mes **solo** entre pares de meses donde reportó de verdad
  en AMBOS extremos — un salto frente a un mes sin reporte real no es una variación genuina, es artefacto del relleno
  interior (LOCF), y se excluye explícitamente.

## Geografía de nodos ISP

Módulo agregado en agosto de 2026, con el mismo estándar de certificación que Líneas Dedicadas: nunca alterar un dato
oficialmente reportado, nunca imputar en silencio, siempre mostrar el motivo cuando algo no se puede resolver.

### Por qué existe, y por qué es un universo distinto de "líneas dedicadas"

`dbo.NodoISP` registra la ubicación física de la infraestructura de acceso de cada prestador — **no** tiene relación 1:1
con la geografía de líneas reportadas (`VALineasDedicadas`): un solo nodo físico puede servir líneas en varias
parroquias distintas. Por eso este módulo vive en tablas, vistas y filtros de dashboard completamente separados de los
de Líneas Dedicadas, y nunca comparten un `dcc.Store` ni una tabla de geografía.

### Parte A — Limpieza de coordenadas (`mart/limpiar_coordenadas_nodo_isp.py`)

`dbo.NodoISP.latitud`/`longitud` son `nvarchar(20)` de texto libre, con formato DMS inconsistente (símbolos de grado
variables, coma o punto decimal, letra de hemisferio en cualquier posición o ausente). El parser
(`convertir_dms_a_decimal`) nunca adivina un valor ambiguo — si no puede convertir con certeza, marca la fila
`es_coordenada_valida = false` con el motivo específico (`coordenada_no_convertible`,
`latitud_fuera_de_rango_ecuador(...)`, etc.), sin descartarla silenciosamente.

**Única excepción deliberada, documentada como un hecho geográfico y no una suposición**:
`inferir_hemisferio_longitud_faltante` — si el texto de longitud no trae ninguna letra de hemisferio (N/S/E/O/W) y el
valor convertido salió positivo, se infiere el signo negativo, porque Ecuador (continental e insular) está 100% al oeste
del meridiano de Greenwich, sin excepción. **Nunca se aplica el mismo criterio a latitud** — Ecuador cruza la línea
ecuatorial, así que ahí sí sería adivinar.

Destino: `capa2.nodo_isp_geocodificado`.

### Parte B — Cruce espacial (`mart/cargar_parroquias.py` + `mart/detectar_discrepancias_geografia_nodo.py`)

**Fuente cartográfica: CONALI** (Comité Nacional de Límites Internos), shapefile a nivel parroquial.
`cargar_parroquias.py` lo carga **una sola vez** (idempotente, `--forzar` para recargar) vía `geopandas`, y precalcula
tres cosas en la misma corrida:

1. `capa2.parroquias_geometria` — geometría íntegra por parroquia (1.052 filas), **sin simplificar** — es la que usa el
   cruce punto-en-polígono real, ahí la precisión completa importa.
2. `capa2.territorio_geometria_nodo` — geometría de cantón y provincia, **disuelta con `gdf.dissolve()`** y
   **simplificada con `shapely.simplify()`** (tolerancia 0.0005°–0.002° según nivel) — exclusivamente para el polígono
   de fondo del mapa del dashboard. Confirmado en producción: el shapefile completo tenía **21,8 millones de vértices**;
   sin simplificar, el navegador se colgaba al elegir Provincia. Tras simplificar: 313 mil vértices (98,6% de
   reducción).
3. Reporta (no descarta) cualquier código de provincia/cantón/parroquia fuera del patrón INEC estándar — CONALI incluye
   zonas especiales sin código numérico convencional (`ISLA`, `ZONA EN ESTUDIO: JUVAL`, etc.).

`detectar_discrepancias_geografia_nodo.py` cruza cada nodo válido contra el shapefile con `shapely.strtree.STRtree` +
`geometry.covers(punto)` (no `.within()` — `covers()` incluye la frontera del polígono). Persiste:

- **`capa2.nodo_isp_geografia_resuelta`** — universo completo de nodos con match espacial (coincidan o no), geografía
  **siempre la derivada de CONALI** (autoritativa). Se reconstruye entera en cada corrida.
- **`calidad.discrepancias_geografia_nodo`** — solo los que discrepan, con el mismo patrón de *workflow* de revisión
  humana persistente que `calidad.conflictos_ruc_peva`.

**Decisión metodológica clave: la comparación es por CANTÓN, no por parroquia exacta.** Comparar por código de parroquia
completo producía 3.976 "discrepancias" sobre 7.021 nodos válidos (56,6%): el 91% de esas resultó ser el mismo lugar con
dos convenciones de código distintas (`dbo.Parroquia` usa una codificación INEC más vieja para la cabecera cantonal —
típicamente `XX01` — que CONALI 2026 — `XX50`). Con la comparación por cantón, el número bajó a 360 discrepancias reales
(5,1%).

**Límite aceptado y documentado**: esto puede dejar pasar una discrepancia real *dentro* del mismo cantón (caso real
encontrado en Sígsig, Azuay). Se acepta este costo a cambio de eliminar el 91% de falso positivo por desfase de
codificación.

### Vistas de `mart` para el dashboard

- **`mart.dim_territorio_nodo`** / **`vw_dashboard_filtros_geograficos_nodo`** — Provincia/Cantón/Parroquia de geografía
  de nodos, construida desde `capa2.nodo_isp_geografia_resuelta` (26 provincias reales: las 24 oficiales +
  `90` "zona en estudio" + `ISLA`). `dim_territorio_nodo` trae columnas planas
  `codigo_provincia`/`codigo_canton`/`codigo_parroquia` — es lo que permite el filtro multi-select independiente del
  dashboard, no un `territorio_id` compuesto que solo admitiera un valor por nivel (ver
  [El dashboard, módulo por módulo](#el-dashboard-módulo-por-módulo)).
- **`mart.vw_geometria_territorio_nodo`** — geometría precalculada (parroquia/cantón/provincia) para el polígono del
  mapa. Nunca se une nada en el dashboard en tiempo de consulta.
- **`mart.vw_nodos_isp_mapa`** — vista principal del mapa: `isp_nombre` se resuelve vía
  `analitico.v_ultimo_periodo_reportado_detalle` (cubre PEVA sin ningún reporte de líneas); `opera_actual` sigue
  viniendo de `mart.dim_prestador` (línea-reporte) a propósito — `NULL` legítimo para quien nunca ha reportado.

## El dashboard, módulo por módulo

Seis páginas Dash (`use_pages=True`), servidas con `gunicorn`, autenticadas con Flask-Login. `pages/inicio.py` (path
`/`) es el panel de selección de módulos tras el login; las otras cinco viven bajo `/sai/`.

- **Evolución** (`pages/evolucion.py`, `/sai/evolucion`): cuentas reportadas y prestadores por mes (**líneas**, no
  barras — series de hasta 180 puntos mensuales), tasa de entrega de reportes, prestadores que nunca han reportado,
  composición (área apilada) y diferencia mensual (barra) por rango de velocidad, ambas respetando Estado de operación y
  Prestador.
- **IHH y participación** (`pages/concentracion.py`, `/sai/concentracion`): evolución histórica del IHH (con alerta de
  *prestador dominante ausente*), cobertura del índice, líder de mercado, CR2/CR4, participación individual, aporte al
  IHH (barras horizontales top 15), y dos gráficos de un solo eje cada uno para el prestador seleccionado
  (participación % / cuentas) — **no** un combo de doble eje: escalas arbitrarias superpuestas invitan a leer una
  correlación visual que puede no existir.
- **Mapa de nodos** (`pages/mapa_nodos.py`, `/sai/mapa-nodos`): ubicación geográfica nacional de nodos de acceso ISP sin
  discrepancia de geografía, coloreados por tipo (primario/secundario), con auto-zoom y polígono del territorio
  seleccionado, más una barra horizontal de nodos por provincia (top 15) — un mapa comunica densidad espacial, no
  compara magnitudes con precisión.
- **Discrepancias de geografía** (`pages/discrepancias_geografia.py`, `/sai/discrepancias-geografia`): nodos cuyo cantón
  reportado en SIETEL no coincide con el cantón real de su coordenada — solo lectura —, más barras de discrepancias por
  provincia real y por estado de revisión.
- **Control** (`pages/control.py`, `/sai/control`): tres tablas de inconsistencias para seguimiento regulatorio —
  prestadores que nunca han reportado (barra por clasificación), prestadores con reporte detenido (histograma de meses
  sin reportar + dispersión antigüedad-vs-peso-histórico en escala log), y variación mensual anómala en cuentas
  reportadas (ranking Top 15 + dispersión temporal con transformación `signo × log₁₀(1+|%|)`, para que un caso de
  +10.000% no aplaste visualmente al resto). Filtros de Provincia/Cantón/Parroquia + Desde/Hasta + Estado/Prestador,
  pero **no aplican igual a las tres secciones** — ver más abajo.

**Descarga a Excel** (`components/ui.py:excel_download_button`): botón junto a cada tabla `dash_ag_grid.AgGrid`,
presente en las tres tablas de Control, Detalle de participación (Concentración), Detalle de nodos (Mapa de nodos) y
Detalle de discrepancias. Exporta exactamente el `rowData` en pantalla (ya filtrado/ordenado), no una consulta nueva —
vía `dcc.send_data_frame(df.to_excel, ...)`, requiere `openpyxl`.

**Selectores de período** (`components/ui.py:month_year_picker`): calendario de meses (`dmc.MonthPickerInput`),
navegación por año, sin nivel de día — reemplazó una lista plana de ~180 opciones (`dcc.Dropdown`) que obligaba a hacer
scroll para llegar al período más reciente.

**Tres familias de filtro geográfico, tres universos de datos distintos, nunca mezclados**:

| Componente                   | Usado por                    | Universo                                                                                 | Nivel geográfico                         | Selección                                               |
|------------------------------|------------------------------|------------------------------------------------------------------------------------------|------------------------------------------|---------------------------------------------------------|
| `territory_filters.py`       | Evolución, Concentración     | Geografía de **líneas** (`mart.dim_territorio`)                                          | Sí (Nacional/Provincia/Cantón/Parroquia) | Única, un valor por nivel                               |
| `node_territory_filters.py`  | Mapa de nodos, Discrepancias | Geografía de **nodos** (`mart.dim_territorio_nodo`, CONALI)                              | No                                       | Múltiple e independiente por Provincia/Cantón/Parroquia |
| `lines_territory_filters.py` | Control                      | Geografía de **líneas** (`mart.dim_territorio`, misma fuente que `territory_filters.py`) | No                                       | Múltiple e independiente                                |

`node_territory_filters.py` y `lines_territory_filters.py` son deliberadamente dos módulos separados y casi idénticos
(no una función genérica parametrizada) — unificarlos exigiría tocar páginas que ya funcionan en producción por un
ahorro de líneas que no vale ese riesgo. Filtran por listas de códigos (`EXISTS` correlacionado, no `JOIN` plano —
`bridge_geografia_territorio` tiene una fila por nivel geográfico por `geografia_id`, un `JOIN` directo multiplicaría
filas).

**Filtros sincronizados entre páginas** (`dcc.Store` fuera de `dash.page_container`, en `app.py`):

- `shared-territory` / `shared-filters`: exclusivos de Evolución/Concentración — geografía de **líneas** reportadas.
- `nodo-shared-territory`: exclusivo de Mapa de nodos/Discrepancias — geografía de **nodos** (CONALI). Forma:
  `{"provincias": [...], "cantones": [...], "parroquias": [...]}` (listas, selección múltiple).
- Control **no** comparte ningún store global de territorio con las demás páginas — su selector de Provincia/Cantón/
  Parroquia es local a la página (`ctrl-territory-selection`); Estado de operación y Prestador tampoco están
  sincronizados con `shared-filters` — Prestador en Control lista el universo **nacional** completo, sin acotar por el
  territorio elegido (simplificación deliberada, no un descuido).

**Por qué los filtros de Control no aplican igual a sus tres secciones** — la vista/consulta fuente de cada una no es
simétrica, esto no es una limitación del dashboard:

- **Nunca han reportado**: SOLO Estado/Prestador. `mart.vw_prestadores_sin_reportar` no tiene columna de geografía
  (SIETEL no la conoce para quien nunca reportó) ni de período (es "alguna vez, sí/no", no una serie de tiempo).
- **Reporte detenido**: territorio = "reportó alguna vez ahí" (`EXISTS` contra `fact_lineas_geografia_mes`, no la
  geografía de su último reporte específico — la vista fuente no la tiene por prestador); Desde/Hasta filtra por fecha
  del **último** reporte, no reemplaza "Meses mínimos sin reportar" (control aparte, mismo sentido pero distinto eje).
- **Variación mensual**: los cinco filtros aplican tal cual, **recalculando** la suma de cuentas dentro del territorio
  elegido antes de comparar mes a mes — mismo principio que `get_evolution_filtrado`.

**Autenticación** (`auth.py`): Flask-Login + bcrypt, guard en `@server.before_request`. Sin autorregistro — altas, bajas
y reseteo de contraseña exclusivamente vía `dashboard/scripts/gestionar_usuarios.py`, corrido con credenciales
administrativas propias (**nunca** con el rol de runtime `dashboard_auth`).

## Requisitos previos

- Docker (Compose v2) sobre el host/VM donde corre este pipeline.
- Acceso de red al servidor SQL Server de SIETEL (puerto 1433).
- Instancia PostgreSQL accesible para: metadata de Airflow, la base analítica `sietel_analitico`, y el dashboard.
- Usuario de SQL Server con permiso de `SELECT` sobre `dbo.VALineasDedicadas`, `dbo.ISP`, `dbo.PermisoVAgregado`,
  `dbo.NodoISP`, `dbo.Parroquia`, `dbo.Ciudad`, `dbo.Provincia`.
- Shapefile de parroquias de CONALI (`ORGANIZACION_TERRITORIAL_PARROQUIAL.*`) — ver
  `mart/data/shapefiles/parroquial/README.md` para el esquema de atributos exacto y el comando de transferencia.
- Ventana de mantenimiento formal y acceso del DBA de SIETEL para modificar índices en producción (ver
  [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)).

## Roles y permisos de PostgreSQL

Ningún rol de aplicación es dueño de más de lo que necesita. Todos se crean **por línea de comandos, directamente en la
VM** — los archivos SQL de este repositorio **asumen que el rol ya existe** y fallan con un error explícito si no es
así.

| Rol                | Dueño de / acceso a                                                                                        | Usado por                                                      |
|--------------------|------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| `sietel_user`      | Esquemas `staging` y `analitico` (Capa 1)                                                                  | Capa 1 (`scripts/*.py`)                                        |
| `mgonzalez`        | Lectura de `analitico`                                                                                     | Consumo externo histórico (Power BI)                           |
| `mart_user`        | Esquemas `capa2`, `mart`, `calidad` (dueño)                                                                | `mart/*.py`, `sql/02_ddl_mart.sql`, `sql/04_ddl_calidad.sql`   |
| `dashboard_lector` | `SELECT` únicamente sobre `mart.*`                                                                         | Dashboard, lectura analítica                                   |
| `dashboard_auth`   | `SELECT`/`INSERT`/`UPDATE` únicamente sobre `auth.usuarios_dashboard`                                      | Dashboard, login/sesión                                        |
| `calidad_lector`   | `SELECT` sobre `calidad.*`                                                                                 | Futuro dashboard de consistencia de datos                      |
| `calidad_revisor`  | `SELECT` sobre `calidad.*` + `UPDATE` solo de columnas de workflow (RUC/PEVA y discrepancias de geografía) | Revisión manual de conflictos RUC/PEVA y discrepancias de nodo |
| `eda_lector`       | `SELECT` sobre `mart.*` y `calidad.*`, `statement_timeout = 30min`                                         | EDA/ML exploratorio (Jupyter), separado del dashboard          |

**Por qué un rol por consumidor, nunca compartir credenciales entre procesos**: mismo principio en todo el proyecto
(`dashboard_lector` vs `dashboard_auth`, `mgonzalez` vs `sietel_user`, `eda_lector` vs `dashboard_lector`) — si algo se
bloquea o hay que revocar acceso, afecta solo a ese consumidor, no al resto.

**`ALTER DEFAULT PRIVILEGES FOR ROLE mart_user`** en `sql/03_ddl_auth.sql`, `sql/04_ddl_calidad.sql` y
`sql/05_roles_eda.sql` es lo que hace que `dashboard_lector`/`calidad_lector`/`eda_lector` sigan teniendo acceso después
de que `aplicar_capa3.py` haga `DROP SCHEMA ... CASCADE` y recree todo.

Orden de aplicación de los scripts de rol/permiso (una sola vez, antes del primer `aplicar_capa3`):

```
sql/00_roles_mart.sql   # requiere que mart_user ya exista
sql/03_ddl_auth.sql     # requiere que mart_user, dashboard_lector, dashboard_auth ya existan
sql/04_ddl_calidad.sql  # requiere que mart_user, calidad_lector, calidad_revisor ya existan
sql/05_roles_eda.sql    # requiere que mart_user, eda_lector ya existan
```

> **Importante, verificado en producción**: estos archivos están diseñados para correr **conectado como
> `mart_user`** (así `CREATE TABLE`/`CREATE SCHEMA` deja a `mart_user` como dueño automáticamente). Si se aplican
> con `sudo -u postgres psql -f ...` (superusuario), los objetos quedan con dueño `postgres` en vez de `mart_user`,
> lo que rompe `INSERT`/`UPDATE` desde `mart/*.py` — el patrón de fix es `ALTER TABLE ... OWNER TO mart_user;`.

## Configuración

### Capa 1 (`scripts/config.py`)

Variables **requeridas** (sin valor por defecto — el script falla explícito si faltan):

| Variable                                              | Descripción                            |
|-------------------------------------------------------|----------------------------------------|
| `SIETEL_SQLSERVER_HOST`                               | Host del servidor SQL Server de SIETEL |
| `SIETEL_SQLSERVER_DATABASE`                           | Base de datos, `SIETEL`                |
| `SIETEL_SQLSERVER_USER` / `SIETEL_SQLSERVER_PASSWORD` | Credenciales de SQL Server             |
| `ANALITICO_PG_HOST`                                   | Host de PostgreSQL analítico           |
| `ANALITICO_PG_USER` / `ANALITICO_PG_PASSWORD`         | Credenciales de PostgreSQL             |
| `ANALITICO_PG_DATABASE`                               | `sietel_analitico`                     |

Con valor por defecto: `SIETEL_SQLSERVER_PORT` (`1433`), `SIETEL_SQLSERVER_ODBC_DRIVER`
(`ODBC Driver 18 for SQL Server`), `ANALITICO_PG_PORT` (`5432`), `LOG_LEVEL` (`INFO`).

`ANIO_INICIO_HISTORICO` (2011) y `ANIO_FIN_HISTORICO` (2025) se definen **únicamente** en `scripts/config.py`.

### Capa 2/3 (`mart/.env`)

| Variable                                                            | Descripción                              |
|---------------------------------------------------------------------|------------------------------------------|
| `MART_USER_USER` / `MART_USER_PASSWORD`                             | Credenciales de `mart_user`              |
| `ANALITICO_PG_HOST` / `ANALITICO_PG_PORT` / `ANALITICO_PG_DATABASE` | Misma instancia PostgreSQL que la Capa 1 |
| `LOG_LEVEL`                                                         | Default `INFO`                           |

### Airflow (`docker/docker-compose.yml`)

Variables propias de Airflow: `AIRFLOW__CORE__FERNET_KEY`, `AIRFLOW__API_AUTH__JWT_SECRET`,
`_AIRFLOW_WWW_USER_USERNAME`, credenciales `AIRFLOW_METADATA_PG_*`. Además, todas las variables de Capa 1 y
`MART_USER_USER`/`MART_USER_PASSWORD` de Capa 2/3.

`AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG=1` limita la concurrencia deliberadamente, para no saturar SQL Server mientras
el índice compuesto no exista en producción.

### Dashboard (`dashboard/.env`, ver `dashboard/.env.example`)

| Variable                                                                                   | Descripción                                                                                          |
|--------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `MART_PG_HOST` / `MART_PG_PORT` / `MART_PG_DATABASE` / `MART_PG_USER` / `MART_PG_PASSWORD` | Conexión de solo lectura, rol `dashboard_lector`                                                     |
| `AUTH_PG_HOST` / `AUTH_PG_PORT` / `AUTH_PG_DATABASE` / `AUTH_PG_USER` / `AUTH_PG_PASSWORD` | Conexión de autenticación, rol `dashboard_auth`                                                      |
| `SECRET_KEY`                                                                               | Firma las cookies de sesión — generar con `python -c "import secrets; print(secrets.token_hex(32))"` |
| `APP_HOST` / `APP_PORT` / `APP_DEBUG`                                                      | Default `0.0.0.0` / `8050` / `false` — **`APP_DEBUG` debe quedar en `false` en producción**          |
| `CACHE_TIMEOUT`                                                                            | Segundos de cache de Flask-Caching, default `300`                                                    |

`dashboard/config.py` falla explícito si falta cualquiera de estas variables.

## Puesta en marcha, paso a paso

1. **Crear los roles de PostgreSQL** por línea de comandos (`mart_user`, `dashboard_lector`, `dashboard_auth`,
   `calidad_lector`, `calidad_revisor`, `eda_lector`).
2. **Aplicar permisos base**, conectado como `mart_user`, en este orden: `sql/00_roles_mart.sql` →
   `sql/03_ddl_auth.sql` → `sql/04_ddl_calidad.sql` → `sql/05_roles_eda.sql`.
3. **Otorgar a `mart_user` lectura sobre `analitico`** (ejecutar como `sietel_user` o superusuario):
   ```sql
   GRANT USAGE ON SCHEMA analitico TO mart_user;
   GRANT SELECT ON analitico.v_ultimo_periodo_reportado_detalle TO mart_user;
   GRANT SELECT ON analitico.v_lineas_dedicadas_resumen TO mart_user;
   GRANT SELECT ON analitico.v_nodo_isp_vigente TO mart_user;
   ```
4. **Levantar Airflow**: `docker compose --env-file ../.env -f docker/docker-compose.yml up -d` (requiere la base de
   metadata ya creada en PostgreSQL bare-metal).
5. **Transferir el shapefile de CONALI** a `mart/data/shapefiles/parroquial/` en la VM de Airflow.
6. **Correr `sietel_usuarios_cuentas_pipeline`** (Capa 1) al menos una vez, para poblar `staging`/`analitico`.
7. **Correr `sietel_mart_pipeline`** (Capa 2/3) — reconstruye `calidad`, `capa2` y `mart` desde cero, incluida la carga
   del shapefile.
8. **Crear el primer usuario del dashboard**:
   ```bash
   cd dashboard/scripts
   python gestionar_usuarios.py crear --username jperez --nombre "Juan Pérez"
   ```
9. **Levantar el dashboard**:
   `docker compose --env-file ../../.env -f dashboard/docker/docker-compose.yml up -d --build`, disponible en el puerto
   `8050`.

## Uso diario

### Vía Airflow (recomendado)

**Capa 1** — Airflow UI → **Admin → Variables** → `sietel_anios_a_cargar`:

| Valor                            | Comportamiento                                                        |
|----------------------------------|-----------------------------------------------------------------------|
| `historico`                      | Carga el rango completo `ANIO_INICIO_HISTORICO`..`ANIO_FIN_HISTORICO` |
| `2025`                           | Carga solo ese año                                                    |
| `2023,2024,2025`                 | Carga esa lista de años                                               |
| (ausente o cualquier otro valor) | Carga solo el año en curso                                            |

Luego, **DAGs** → `sietel_usuarios_cuentas_pipeline` → *Trigger DAG*.

**Capa 2/3** — **DAGs** → `sietel_mart_pipeline` → *Trigger DAG*, después de cada actualización relevante de Capa 1, o
cuando se necesite refrescar el dashboard.

### Vía CLI (pruebas puntuales / smoke tests)

```bash
# Capa 1 — aplicar esquema y cargar dimensiones (primera vez)
python scripts/aplicar_esquema.py
python scripts/cargar_dimensiones.py
python scripts/cargar_nodo_isp.py

# Capa 1 — cargar un año completo / un solo mes
python scripts/cargar_hechos_anio.py --anio 2025
python scripts/cargar_hechos_anio.py --anio 2025 --mes 12

# Capa 1 — certificación cruzada / backfill de códigos administrativos
python scripts/validar_carga.py --anios 2025
python scripts/sincronizar_codigos_administrativos.py

# Capa 2/3 — reconstruir todo el mart manualmente, en orden
cd mart
python detectar_conflictos_peva.py
python construir_capa2.py
python limpiar_coordenadas_nodo_isp.py
python cargar_parroquias.py              # --forzar para recargar el shapefile
python detectar_discrepancias_geografia_nodo.py
python aplicar_capa3.py

# Dashboard — administración de usuarios
cd dashboard/scripts
python gestionar_usuarios.py listar
python gestionar_usuarios.py crear --username jperez --nombre "Juan Pérez"
python gestionar_usuarios.py desactivar --username jperez
python gestionar_usuarios.py resetear-password --username jperez
```

> `gestionar_usuarios.py` pide la contraseña nueva por `getpass` (dos veces) — nunca por argumento ni variable de
> entorno. El "usuario administrativo" que pide al conectar debe ser el dueño del esquema `auth` o un superusuario
> puntual — **nunca** `dashboard_auth` (el rol de runtime de la app).

## Modelo de datos

**Esquema `staging`** (Capa 1, tablas físicas):

| Tabla                         | Contenido                                                                                                                                                 |
|-------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `va_lineas_dedicadas_resumen` | Hechos agregados de líneas dedicadas: una fila por `(peva_codigo, par_codigo, periodoNumero, anio, tipoEnlace, tipoCliente, nivelComparticion, portador)` |
| `dim_isp`                     | Dimensión ISP, versionada (SCD Tipo 2)                                                                                                                    |
| `dim_permiso_va_agregado`     | Dimensión de permisos de prestador, versionada (SCD Tipo 2)                                                                                               |
| `dim_nodo_isp`                | Dimensión de nodos ISP, versionada (SCD Tipo 2), con códigos INEC de parroquia/cantón/provincia                                                           |
| `control_cargas`              | Auditoría de cada corrida: tipo, año, filas, estado, errores                                                                                              |
| `historial_correcciones`      | Snapshot (JSONB) de cada fila de líneas dedicadas cuya certificación de contenido cambió entre cargas                                                     |

**Esquema `analitico`** (Capa 1, vistas de consumo):

| Vista                                | Uso                                                                                                                                                                                                            |
|--------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `v_lineas_dedicadas_resumen`         | Serie histórica completa de líneas dedicadas, dimensiones resueltas por vigencia temporal. Solo prestadores con actividad reportada                                                                            |
| `v_ultimo_periodo_reportado_detalle` | Último período reportado por cada prestador vigente + estado administrativo. Incluye prestadores sin ningún reporte (`tiene_reportes = false`) vía `LEFT JOIN` — única fuente que conoce a quien nunca reportó |
| `v_nodo_isp_vigente`                 | Nodos ISP vigentes (`dbo.NodoISP`, sin `NodoISP_Auxiliar`), coordenadas crudas sin limpiar, con códigos INEC                                                                                                   |

**Esquema `calidad`** (Capa 2):

| Objeto                         | Contenido                                                                                                    |
|--------------------------------|--------------------------------------------------------------------------------------------------------------|
| `conflictos_ruc_peva`          | RUC con múltiples PEVA en conflicto, clasificados (A/B/C) + workflow de revisión persistente                 |
| `vw_pevas_excluidos`           | PEVA del Grupo A confirmados, que `construir_capa2.py` excluye de la serie consolidada                       |
| `discrepancias_geografia_nodo` | Nodos ISP cuyo cantón reportado no coincide con el derivado de su coordenada (CONALI) + workflow de revisión |

**Esquema `capa2`** (Capa 2):

| Tabla                          | Contenido                                                                                                                                           |
|--------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `lineas_dedicadas_consolidado` | Serie mensual completa por PEVA/geografía/tipoEnlace/tipoCliente/nivelComparticion/portador, LOCF solo interior, flags `es_reportado`/`es_imputado` |
| `nodo_isp_geocodificado`       | Nodos con latitud/longitud convertidas a decimal + validadas (Parte A geografía de nodos)                                                           |
| `parroquias_geometria`         | Geometría íntegra por parroquia (CONALI, 1.052 filas), sin simplificar — fuente del cruce punto-en-polígono real                                    |
| `territorio_geometria_nodo`    | Geometría de cantón/provincia, disuelta y simplificada — exclusivamente para el polígono del mapa del dashboard                                     |
| `nodo_isp_geografia_resuelta`  | Universo completo de nodos con match espacial (coincidan o no con lo reportado), geografía CONALI                                                   |

**Esquema `mart`** (Capa 3): dimensiones (`dim_periodo`, `dim_prestador`, `dim_geografia`, `dim_territorio`,
`dim_territorio_nodo`), tablas puente (`bridge_geografia_territorio`), tablas de hechos de líneas dedicadas
(`fact_lineas_geografia_mes`, `fact_lineas_velocidad_mes`, `fact_resumen_mercado_mes`, `fact_velocidad_mercado_mes`,
`fact_participacion_mercado`, `fact_ihh_geografico`), vistas de cumplimiento (`vw_prestadores_sin_reportar`,
`vw_prestadores_reporte_detenido`), vistas de geografía de nodos (`vw_nodos_isp_mapa`, `vw_geometria_territorio_nodo`,
`vw_dashboard_filtros_geograficos_nodo`), y las vistas `vw_dashboard_*` que consume directamente el dashboard.

**Columnas por rango de velocidad** (`lineas_dl_*` para bajada, `lineas_ul_*` para subida) cuentan **líneas/cuentas**,
no usuarios finales:

| Columna         | Rango (Kbps)        | Referencia         |
|-----------------|---------------------|--------------------|
| `sin_datos`     | NULL o 0            | No reportado       |
| `menos_1mbps`   | < 1.024             | Brecha digital     |
| `1_10mbps`      | 1.024 – 10.239      | Umbral mínimo ITU  |
| `10_30mbps`     | 10.240 – 30.719     | Umbral básico OCDE |
| `30_100mbps`    | 30.720 – 102.399    | Umbral UE          |
| `100mbps_1gbps` | 102.400 – 1.048.575 | Ultra banda ancha  |
| `1gbps_o_mas`   | ≥ 1.048.576         | Gigabit            |

## Códigos administrativos y sincronización

Desde el 22-jul-2026, `va_lineas_dedicadas_resumen` incluye `codigo_provincia`, `codigo_ciudad` y
`codigo_parroquia` (VARCHAR, no INTEGER, para preservar ceros a la izquierda), tomados de
`Provincia.codigo`/`Ciudad.codigoCiudad`/`Parroquia.codigoParroquia` en SQL Server. Desde el 07-ago-2026, el mismo
criterio se aplicó a `dim_nodo_isp`. En ambos casos, **no forman parte de `COLUMNAS_HASH`/`COLUMNAS_VERSIONABLES`** —
son metadata derivada de `par_codigo`, no parte de la llave natural ni de las métricas medidas.

Los años cargados **antes** de este cambio necesitan un backfill puntual —
`scripts/sincronizar_codigos_administrativos.py` (idempotente, no cableado al DAG). Este backfill **no** modifica
`hash_contenido` ni genera entradas en `historial_correcciones`.

## Historial de correcciones

`staging.historial_correcciones`, poblada por el trigger `trg_registrar_correccion_resumen`, registra un snapshot
completo (JSONB) de la fila anterior cada vez que `hash_contenido` cambia entre una carga y otra.

**Correcciones puntuales aplicadas en producción sobre `mart` sin esperar al próximo refresco completo**
(`sql/06` a `sql/08`, cada una con su verificación documentada dentro del propio archivo):

| Archivo                                        | Qué corrige                                                                                                                                                                |
|------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `06_patch_vw_prestadores_sin_reportar.sql`     | Agrega `fuera_de_gracia` y `clasificacion_incumplimiento` sin esperar al próximo refresco completo                                                                         |
| `07_patch_vw_prestadores_reporte_detenido.sql` | Corrige 13 falsos positivos: usaba el último período crudo como referencia en vez de uno con margen de 3 meses                                                             |
| `08_patch_fact_ihh_geografico.sql`             | Alerta de *prestador dominante ausente* — tres iteraciones hasta acotarla a NACIONAL (v2 y v3 producían falsos positivos por período de existencia y por nivel geográfico) |

**Bug crítico corregido en `_cambio_relevante()`** (`cargar_dimensiones.py` y `cargar_nodo_isp.py`, 07-ago-2026):
comparaba claves de diccionario con el *case* exacto de SQL Server (`tipoNodo`, `Resolucion`, `nombreComercial`)
contra claves de Postgres siempre plegadas a minúscula — el *mismatch* hacía que **toda** fila se detectara como cambio
real, siempre, disparando una nueva versión SCD2 innecesaria en cada corrida. Confirmado en producción:
`dim_permiso_va_agregado` había acumulado 7 versiones espurias por PEVA (11.655 → 1.665 filas tras la remediación con
`scripts/remediar_versiones_espurias_scd2.py`, que fusiona solo versiones *consecutivas* idénticas, preservando
cualquier cambio real intercalado); `dim_nodo_isp` acumuló 1 versión espuria por nodo (8.606 → 8.606 nodos, cada uno con
exactamente 2 versiones antes de remediar).

**Correcciones aplicadas en el dashboard (agosto de 2026), documentadas aquí por el mismo criterio que las de arriba —
no son detalles cosméticos, cambiaron resultados numéricos**:

- **Correlación SQL incorrecta en el filtro de territorio de "Reporte detenido" (Control, 12-ago-2026)**: la cláusula
  `EXISTS` escribía `f.prestador_id = prestador_id` (el lado derecho sin calificar) esperando correlacionar contra la
  tabla exterior — pero como `fact_lineas_geografia_mes` (alias `f`, la tabla MÁS interna) también tiene una columna
  `prestador_id`, Postgres resolvió el nombre suelto contra `f` misma. La condición se volvió una tautología
  (`f.prestador_id = f.prestador_id`, siempre verdadera), así que el filtro preguntaba "¿existe ALGUNA fila en ese
  territorio en toda la tabla nacional?" en vez de "¿ESTE prestador reportó ahí?" — confirmado en producción vía logging
  temporal: el resultado se quedaba en 548 filas sin importar el territorio elegido. Corregido con un alias explícito
  (`pr`) en la tabla exterior.
- **`dcc.Input(type="number")` perdía el valor al usar las flechas +/-** (Control, 12-ago-2026) — comportamiento
  conocido del spinner nativo del navegador combinado con un callback de Python sin `debounce`. Reemplazado por
  `dmc.NumberInput` (`components/ui.py:numeric_stepper`).
- **Selector "Nivel geográfico" en Mapa de nodos/Discrepancias** rediseñado a Provincia/Cantón/Parroquia siempre
  visibles, multi-select independiente (11-ago-2026) — mismo patrón replicado luego para Control
  (`lines_territory_filters.py`, 12-ago-2026), sobre la geografía de líneas en vez de la de nodos.

## Rendimiento e índice de SQL Server

`dbo.VALineasDedicadas` requiere un índice compuesto cubridor (`IX_VALineasDedicadas_Analitico`) para que la extracción
mensual sea viable:

```sql
CREATE NONCLUSTERED INDEX [IX_VALineasDedicadas_Analitico]
ON [dbo].[VALineasDedicadas] (anio, periodoNumero, peva_codigo, par_codigo)
INCLUDE (periodoNombre, tipoEnlace, tipoCliente, nivelComparticion,
         portador, regional, numeroUsuarios, downLink, upLink);
```

El `INCLUDE` debe cubrir **todas** las columnas que `SQL_EXTRAER_HECHOS_ANIO` proyecta o agrupa. Cambiar este índice en
el servidor de producción requiere una ventana de mantenimiento formal.

## Validación y certificación de datos

`validar_carga.py` recalcula el agregado completo desde SQL Server — mes a mes — y compara un hash MD5 por fila contra
lo almacenado en PostgreSQL. Chequeos adicionales: dimensiones SCD sin versiones vigentes duplicadas, y vista de consumo
sin filas duplicadas por el `JOIN` de vigencia temporal (llave natural completa de 8 columnas). El resultado se imprime
como reporte consolidado (✅/❌) y se registra en `staging.control_cargas`.

`sql/02_ddl_mart.sql` incluye su propio bloque de validaciones (sección 17, fuera de la transacción principal),
incluyendo invariantes de la metodología de datos reales: ningún prestador sin reporte real ese mes debe tener
`participacion_porcentaje`/`aporte_ihh` distinto de `NULL`, cobertura siempre entre 0 y 100, `CR2 ≤ CR4 ≤ 100`.

La geografía de nodos se verifica manualmente contra Postgres real en cada cambio de esquema. Las consultas y callbacks
del dashboard se prueban con datos simulados que cubren casos límite reales (rangos extremos observados en producción,
nombres nulos, valores mixtos de mayúsculas) antes de cada entrega — no solo el camino feliz — desde que un patrón de
correlación SQL incorrecto pasó una prueba superficial (ver
[Historial de correcciones](#historial-de-correcciones)).

## Calidad de datos conocida

**Líneas dedicadas:**

- **Patrón append-only sin deduplicación**: verificado con un caso que aparece 4.843 veces entre 2015-2024 en la misma
  dirección. El pipeline **no deduplica** silenciosamente.
- **Campo `opera` con codificación heredada inconsistente**: la mayoría usa categorías descriptivas, un subconjunto usa
  `SI`/`NO`/`-` — causa raíz de la mayoría de conflictos "RUC con múltiples PEVA" (Grupo A).
- **Cadencia de reporte no uniforme entre prestadores**: un prestador grande puede reportar trimestralmente durante
  períodos extensos — los "picos" en gráficas de evolución son la cadencia real, no un error del pipeline.
- **`v_ultimo_periodo_reportado_detalle` no tiene geografía para prestadores sin reportes**: el KPI *"Nunca han
  reportado"* (Evolución) y la sección "Nunca han reportado" (Control) solo están disponibles a nivel Nacional por esta
  razón estructural — ver [El dashboard, módulo por módulo](#el-dashboard-módulo-por-módulo).
- **Lista de columnas versionables SCD no cerrada formalmente**: `COLUMNAS_VERSIONABLES_ISP`/`_PERMISO`/`_NODO_ISP`
  son una propuesta inicial pendiente de confirmar con Mercados.
- **RUC con múltiples PEVA de nombre distinto (Grupo C)**: sin resolución automática — cola de revisión manual.

**Geografía de nodos ISP:**

- **`dbo.Parroquia` usa codificación INEC más vieja que CONALI 2026**: causa raíz de que la comparación de discrepancias
  sea por cantón, no por parroquia exacta.
- **~18,4% de coordenadas de nodo no se pueden convertir** — quedan marcadas `es_coordenada_valida = false` con el
  motivo, nunca descartadas silenciosamente ni "corregidas" con una suposición.
- **Ambigüedad geométrica en fronteras compartidas**: un nodo capturado exactamente sobre un vértice compartido entre
  dos parroquias adyacentes puede resolver a cualquiera de las dos, según el orden interno de `STRtree` — trade-off
  aceptado (la alternativa, `.within()`, deja esos nodos sin ningún match).
- **`mgonzalez`/Power BI**: posible misma fragilidad de permisos que ya se corrigió para `mart_user`
  (`ALTER DEFAULT PRIVILEGES` no está capturado en ningún `.sql` versionado para este rol) — **sin confirmar todavía**.

**Control:**

- **"Prestador" no está acotado por el territorio elegido** — lista el universo nacional completo, a diferencia de
  Evolución/Concentración, donde sí se acota. Simplificación deliberada, no un descuido — ver
  [El dashboard, módulo por módulo](#el-dashboard-módulo-por-módulo).
- **Umbral de variación mensual (30% por defecto) no está validado estadísticamente** — es un punto de partida razonable
  para señalar algo revisable, ajustable en la página, no un límite estadístico riguroso.

## Seguridad del dashboard

- Sesión de Flask-Login, cookies firmadas con `SECRET_KEY` propio (nunca en Git).
- Contraseñas con `bcrypt`, nunca texto plano.
- Sin autorregistro — toda gestión de usuarios pasa por `dashboard/scripts/gestionar_usuarios.py`, con credenciales
  administrativas separadas del rol de runtime.
- El guard de autenticación (`@server.before_request`) bloquea **todas** las rutas salvo `/login`, `/logout` y los
  endpoints internos de Dash — se aplica antes de que Dash sirva cualquier layout.
- Mismo mensaje de error para usuario inexistente, contraseña incorrecta o usuario inactivo.
- `APP_DEBUG=false` obligatorio en producción.
- Servido con `gunicorn`, nunca con el servidor de desarrollo de Flask/Dash.
- **Pendiente**: `dashboard/templates/login.html` no tiene token CSRF — Flask-Login no lo provee por defecto. Riesgo
  bajo (formulario de login, no una acción de estado con sesión ya activa), pero es una desviación de buena práctica no
  resuelta todavía — ver [Hoja de ruta](#hoja-de-ruta--pendientes).

## Pruebas de integración

`tests/verificar_pipeline.py` valida contra el entorno real (solo Capa 1 por ahora):

```bash
python tests/verificar_pipeline.py --anios 2026
python tests/verificar_pipeline.py --anios 2024 2025 2026 --verbose
```

Verifica conectividad a ambas bases, existencia de tablas/vistas esperadas del esquema de Capa 1, y delega la
certificación cruzada en `validar_carga.validar_anios()`.

> **Cobertura conocida como incompleta:** no incluye `staging.dim_nodo_isp`, ni ningún objeto de los esquemas
> `mart`/`capa2`/`calidad` (Capa 2/3, incluida toda la geografía de nodos) todavía. Tampoco hay una suite automatizada
> para el dashboard — las verificaciones de `pages/`/`services/queries.py` se hacen con datos simulados en aislamiento
> antes de cada entrega, no como parte de este archivo.

## Documentación relacionada

| Documento                                                           | Contenido                                                               |
|---------------------------------------------------------------------|-------------------------------------------------------------------------|
| `Informe_Hallazgos_SIETEL.docx`                                     | Por qué se descartó `VAReporteUsuariosCuentas`, patrón append-only      |
| `Propuesta_Modificacion_SIETEL.pptx`                                | Propuesta de correcciones estructurales para el equipo de SIETEL        |
| `Especificacion_Tecnica_SIETEL.docx`                                | Diseño SCD Tipo 2, lógica de carga, plan de migración                   |
| `Instruccion_Tecnica_Indice_SIETEL_v1.3.docx`                       | Script de índice listo para el DBA de producción                        |
| `mart/data/shapefiles/parroquial/README.md`                         | Esquema de atributos del shapefile CONALI, comando de transferencia     |
| *Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx* | Fuente de verdad de qué roles de PostgreSQL existen y cuándo se crearon |

Patrones de diseño (certificación de contenido vía hash, carga por lotes, unión y simplificación de geometría vía
`geopandas`/`shapely`, punto-en-polígono vía `STRtree`) tomados como referencia de
[`Zerausir/samm_pipeline`](https://github.com/Zerausir/samm_pipeline), un pipeline hermano con el que se comparte
infraestructura de VMs y versión de Airflow. El estilo visual del panel de opciones del dashboard (`pages/inicio.py`)
se inspiró en `Zerausir/tablero`.

## Hoja de ruta / pendientes

- [ ] Aplicar el índice `IX_VALineasDedicadas_Analitico` en el servidor de producción de SIETEL.
- [ ] Vista de auditoría de líneas potencialmente duplicadas (separada del dato certificado).
- [ ] Cerrar formalmente con el área de Mercados la lista de columnas versionables SCD (ISP, PermisoVAgregado, NodoISP).
- [ ] Ampliar `tests/verificar_pipeline.py` para cubrir `historial_correcciones`,
  `v_ultimo_periodo_reportado_detalle`, `dim_nodo_isp`, y todos los objetos de `mart`/`capa2`/`calidad`.
- [ ] Documentar formalmente las variables `AIRFLOW_METADATA_PG_*` en un archivo de referencia de configuración.
- [ ] Incorporar datos de internet móvil (fuente aún no identificada en SIETEL).
- [ ] Pantalla de consistencia de datos sobre `calidad.conflictos_ruc_peva` (Grupos B/C pendientes de revisión manual) y
  `calidad.discrepancias_geografia_nodo`, con el rol `calidad_revisor` — hoy la revisión de ambas colas ocurre fuera de
  OBTEL.
- [ ] Verificar si `mgonzalez`/Power BI tiene la misma fragilidad de permisos ya corregida para `mart_user`
  (`ALTER DEFAULT PRIVILEGES` no capturado en Git para ese rol).
- [ ] Investigar el caso Sígsig (discrepancia real dentro del mismo cantón, no capturada por el criterio actual de
  comparación) para evaluar si vale la pena un segundo nivel de detección intra-cantón.
- [ ] Token CSRF en `dashboard/templates/login.html` — ver [Seguridad del dashboard](#seguridad-del-dashboard).
- [ ] Evaluar si "Prestador" en Control debería acotarse al territorio elegido (hoy lista el universo nacional).
- [ ] Explorar una fuente de geografía para "Nunca han reportado" (Control) — hoy es un límite estructural sin datos
  disponibles en SIETEL para resolverlo; no hay una vía identificada todavía.
- [ ] Suite de pruebas automatizada para el dashboard (hoy las verificaciones son manuales, con datos simulados, antes
  de cada entrega).

## Dónde obtener ayuda

Para dudas sobre este proyecto (pipeline o dashboard), contactar al equipo de analítica de la Dirección de Mercados.
Para problemas de acceso o desempeño del propio SIETEL, canalizar a través de
`Propuesta_Modificacion_SIETEL.pptx` y el equipo técnico de SIETEL.

## Mantenedores

- **Marcos González Auhing** — Dirección de Mercados, ARCOTEL.
- **Iván Suárez Fabara** — Dirección de Mercados, ARCOTEL.