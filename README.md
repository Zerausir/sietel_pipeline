# OBTEL — Observatorio de Telecomunicaciones

Sistema de datos de extremo a extremo para el módulo **Líneas Dedicadas de Internet Fijo** de **SIETEL** (el sistema
regulatorio de ARCOTEL sobre SQL Server): extrae, certifica, modela y expone en un dashboard analítico la información
que los prestadores de servicios de telecomunicaciones reportan mensualmente al regulador — como insumo tanto para el
análisis de mercado como para el control y la regulación del sector.

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

**Capa 2/3** — `mart/requirements.txt` (rangos, no versión fija)

[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00)](https://www.sqlalchemy.org/)
[![psycopg](https://img.shields.io/badge/psycopg%5Bbinary%5D-3.x-336791?logo=postgresql&logoColor=white)](https://www.psycopg.org/psycopg3/)
[![python-dotenv](https://img.shields.io/badge/python--dotenv-1.x-ECD53F)](https://pypi.org/project/python-dotenv/)

> Rangos exactos: `SQLAlchemy>=2.0,<3`, `psycopg[binary]>=3.2,<4`, `python-dotenv>=1.0,<2`.

**Dashboard** — `dashboard/requirements.txt`

[![Dash](https://img.shields.io/badge/Dash-4.4.1-008DE4?logo=plotly&logoColor=white)](https://dash.plotly.com/)
[![dash-ag-grid](https://img.shields.io/badge/dash--ag--grid-35.3.0-1D1D1D)](https://github.com/plotly/dash-ag-grid)
[![pandas](https://img.shields.io/badge/pandas-3.0.5-150458?logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0.51-D71F00)](https://www.sqlalchemy.org/)
[![psycopg](https://img.shields.io/badge/psycopg%5Bbinary%5D-3.3.4-336791?logo=postgresql&logoColor=white)](https://www.psycopg.org/psycopg3/)
[![python-dotenv](https://img.shields.io/badge/python--dotenv-1.2.2-ECD53F)](https://pypi.org/project/python-dotenv/)
[![Flask-Caching](https://img.shields.io/badge/Flask--Caching-2.4.1-000000?logo=flask&logoColor=white)](https://flask-caching.readthedocs.io/)
[![Flask-Login](https://img.shields.io/badge/Flask--Login-0.6.3-000000?logo=flask&logoColor=white)](https://flask-login.readthedocs.io/)
[![bcrypt](https://img.shields.io/badge/bcrypt-5.0.0-4B8BBE)](https://pypi.org/project/bcrypt/)
[![gunicorn](https://img.shields.io/badge/gunicorn-26.0.0-499848?logo=gunicorn&logoColor=white)](https://gunicorn.org/)

---

## Tabla de contenidos

- [Qué hace este proyecto](#qué-hace-este-proyecto)
- [Por qué existe](#por-qué-existe)
- [Arquitectura general](#arquitectura-general)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Las tres capas, en detalle](#las-tres-capas-en-detalle)
    - [Capa 1 — Pipeline SIETEL → PostgreSQL (staging / analitico)](#capa-1--pipeline-sietel--postgresql-staging--analitico)
    - [Capa 2 — Consolidación y calidad (capa2 / calidad)](#capa-2--consolidación-y-calidad-capa2--calidad)
    - [Capa 3 — Mart analítico (mart)](#capa-3--mart-analítico-mart)
    - [Dashboard (Dash + Flask-Login)](#dashboard-dash--flask-login)
- [Principio metodológico: nunca imputar para medir concentración de mercado](#principio-metodológico-nunca-imputar-para-medir-concentración-de-mercado)
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

- Extrae y **agrega en el propio SQL Server** (nunca transfiere el detalle crudo) los datos de
  `dbo.VALineasDedicadas` — la tabla de origen verdaderamente auditable de líneas dedicadas, reportada mes a mes por
  cada prestador.
- Certifica cada carga con un **hash MD5 recalculado desde el origen**: no solo verifica que la cantidad de filas
  coincida, verifica que el **valor** de cada fila coincida.
- Versiona las dimensiones `ISP` y `PermisoVAgregado` con **SCD Tipo 2**, para poder resolver el estado de un prestador
  en cualquier punto del histórico, aunque SIETEL solo exponga su estado *actual*.
- Detecta y clasifica automáticamente **RUC con múltiples PEVA en conflicto** (duplicados por migración de codificación
  heredada, secuencias del mismo titular, nombres distintos bajo el mismo RUC), con un flujo de revisión humana
  persistente para los casos que no se pueden resolver solos.
- Reconstruye una **serie mensual completa** (`capa2`) para cada PEVA, rellenando huecos **solo hacia el interior**
  (nunca extrapola hacia adelante) y marcando de forma explícita, fila por fila, qué es un reporte real y qué es
  relleno — sin mezclar nunca ambos conceptos en un dashboard de decisión regulatoria.
- Calcula **IHH, CR2, CR4 y participación de mercado exclusivamente sobre datos reportados** — nunca sobre datos
  imputados —, publicando siempre un indicador de cobertura junto al índice.
- Publica un **dashboard web** (Dash + PostgreSQL) con autenticación propia — OBTEL — para que la Dirección de Mercados
  analice evolución del mercado, cumplimiento de reporte y concentración, como insumo tanto para el análisis de mercado
  como para el control y la regulación del sector, sin depender de Power BI para el día a día.

## Por qué existe

`dbo.VAReporteUsuariosCuentas` (la tabla que en teoría ya resume esta información) fue descartada como fuente: es una
tabla física sin ningún proceso de cálculo auditable en el esquema de SIETEL — sin vista, trigger ni procedimiento
almacenado que explique cómo se puebla —, por lo que sus inconsistencias no son trazables al origen. Ese hallazgo está
documentado formalmente en `Informe_Hallazgos_SIETEL.docx`.

`dbo.VALineasDedicadas` sí es un dato crudo auditable: una fila por línea dedicada, por cliente, por período, reportada
directamente por el prestador. Todo este proyecto se construye sobre esa fuente.

## Arquitectura general

```
[SQL Server SIETEL — dbo.VALineasDedicadas, dbo.ISP, dbo.PermisoVAgregado, ...]
        │  pyodbc + ODBC Driver 18 for SQL Server
        │  Fix OpenSSL UnsafeLegacyRenegotiation (SQL Server 2008 R2 no soporta RFC 5746)
        │  GROUP BY ejecutado en SQL Server, particionado por mes — nunca se transfiere detalle crudo
        ▼
┌───────────────────────────── CAPA 1 ─────────────────────────────┐
│ DAG: sietel_usuarios_cuentas_pipeline                             │
│ esquema → dimensiones SCD Tipo 2 → años → hechos (mapeado) →      │
│ validación cruzada certificada (hash MD5)                         │
│ Destino: PostgreSQL, esquemas staging (tablas) y analitico (vistas)│
└────────────────────────────────────────────────────────────────────┘
        ▼
┌───────────────────────────── CAPA 2/3 ────────────────────────────┐
│ DAG: sietel_mart_pipeline                                         │
│ 1) detectar_conflictos_peva  → esquema calidad                    │
│ 2) construir_capa2           → capa2.lineas_dedicadas_consolidado  │
│    (relleno LOCF solo interior, marca es_reportado/es_imputado)   │
│ 3) aplicar_capa3             → esquema mart (sql/02_ddl_mart.sql)  │
│    IHH/participación/evolución solo con datos reales + cobertura  │
└────────────────────────────────────────────────────────────────────┘
        ▼
┌───────────────────────────── DASHBOARD ───────────────────────────┐
│ Dash + Flask-Login + gunicorn, contenedor propio                  │
│ Páginas: Evolución del mercado · IHH y participación               │
│ Lee exclusivamente mart.* (rol de solo lectura dashboard_lector)   │
└────────────────────────────────────────────────────────────────────┘
        ▼
Power BI (reportes existentes) + Dashboard propio (uso diario, Dirección de Mercados)
```

**Por qué `pyodbc` y no `pymssql`:** el servidor SIETEL exige una negociación TLS que FreeTDS (usado internamente por
`pymssql`) rechaza durante el handshake — confirmado con TDSDUMP, error "login packet rejected". El driver ODBC oficial
de Microsoft (el mismo stack que usa SQL Server Management Studio) sí negocia correctamente.

**Por qué el fix de OpenSSL:** SQL Server 2008 R2 no soporta RFC 5746 (renegociación TLS segura), que OpenSSL 3.x exige
por defecto. Sin el fix, la conexión falla con `SSL routines::unsafe legacy renegotiation disabled`. El fix se aplica
solo dentro del contenedor de `docker/Dockerfile` — no debe extenderse nunca a un contenedor compartido con otro
pipeline.

**Por qué la metadata de Airflow no corre en un contenedor PostgreSQL propio:** vive en la instancia PostgreSQL
bare-metal ya existente (misma instancia que aloja `sietel_analitico`), en una base separada — facilita backups
institucionales y evita levantar una instancia de base de datos adicional solo para metadata.

**Por qué `capa2` es una tabla física reconstruida, no una vista:** el relleno LOCF interior (ver
[más abajo](#principio-metodológico-nunca-imputar-para-medir-concentración-de-mercado)) requiere ventanas ordenadas
sobre toda la serie histórica de cada PEVA — recalcularlo en cada consulta del dashboard sería inviable en tiempo de
respuesta. Se reconstruye por completo (`TRUNCATE` + regeneración) en cada corrida del DAG `sietel_mart_pipeline`, no se
actualiza incrementalmente.

## Estructura del repositorio

```
sietel_pipeline/
├── dags/
│   ├── sietel_usuarios_cuentas_pipeline.py   # Capa 1: SQL Server → staging/analitico
│   └── sietel_mart_pipeline.py               # Capa 2/3: conflictos PEVA → capa2 → mart
├── scripts/                                  # Capa 1
│   ├── config.py                             # Conexiones, ANIO_INICIO_HISTORICO=2011 / ANIO_FIN_HISTORICO=2025
│   ├── aplicar_esquema.py                    # Ejecuta sql/01_ddl_postgres.sql de forma idempotente
│   ├── cargar_dimensiones.py                 # SCD Tipo 2: dim_isp y dim_permiso_va_agregado
│   ├── cargar_hechos_anio.py                 # Extracción agregada mes a mes + upsert certificado por hash
│   ├── sincronizar_codigos_administrativos.py# Backfill idempotente de códigos INEC, standalone (fuera del DAG)
│   └── validar_carga.py                      # Certificación cruzada SQL Server vs PostgreSQL
├── mart/                                     # Capa 2/3
│   ├── detectar_conflictos_peva.py           # Detecta/clasifica RUC con múltiples PEVA, resuelve Grupo A
│   ├── construir_capa2.py                    # Reconstruye capa2.lineas_dedicadas_consolidado (LOCF interior)
│   ├── aplicar_capa3.py                      # Aplica sql/02_ddl_mart.sql completo (protocolo simple de Postgres)
│   └── requirements.txt
├── sql/
│   ├── 00_roles_mart.sql                     # Permisos de mart_user (dueño de capa2/mart/calidad)
│   ├── 01_ddl_postgres.sql                   # DDL Capa 1: tablas, índices, dimensiones, vistas, trigger
│   ├── 02_ddl_mart.sql                       # DDL Capa 3: esquema mart completo (~2.500 líneas, ver más abajo)
│   ├── 03_ddl_auth.sql                       # Esquema auth: login del dashboard (Flask-Login + bcrypt)
│   └── 04_ddl_calidad.sql                    # Esquema calidad: conflictos RUC/PEVA, workflow de revisión
├── dashboard/                                 # Aplicación Dash
│   ├── app.py                                # Layout raíz, stores compartidos entre páginas, navegación
│   ├── auth.py                                # Flask-Login + bcrypt, blueprint /login /logout
│   ├── config.py                             # Settings (dataclass), variables de entorno del dashboard
│   ├── extensions.py                         # Instancia compartida de Flask-Caching
│   ├── requirements.txt
│   ├── .env.example
│   ├── assets/
│   │   └── styles.css                        # Tema visual (variables CSS, tarjetas KPI, grids de filtros)
│   ├── components/
│   │   ├── ui.py                              # Helpers de UI: tarjetas KPI con tooltip, gráficos vacíos, formato
│   │   ├── territory_filters.py               # Filtro geográfico en cascada, sincronizado entre páginas
│   │   └── filters_shared.py                  # Filtro de Estado de operación / Prestador, sincronizado
│   ├── pages/
│   │   ├── evolucion.py                       # Página "Evolución del mercado"
│   │   └── concentracion.py                   # Página "IHH y participación"
│   ├── services/
│   │   ├── database.py                        # Engines SQLAlchemy (mart_lector, auth) + validadores de esquema
│   │   └── queries.py                         # Todas las consultas cacheadas contra mart.*
│   ├── scripts/
│   │   └── gestionar_usuarios.py              # CLI administrativo: alta/baja/reset de usuarios del dashboard
│   ├── templates/
│   │   └── login.html                         # Página de login (Flask puro, no una página de Dash)
│   └── docker/
│       ├── Dockerfile                         # python:3.14-slim + gunicorn
│       └── docker-compose.yml
├── docker/                                     # Contenedor de Airflow (Capas 1 y 2/3)
│   ├── Dockerfile                             # Airflow 3.3.0 / Python 3.14 + pyodbc + ODBC Driver 18 + fix TLS
│   └── docker-compose.yml
├── tests/
│   └── verificar_pipeline.py                  # Pruebas de integración end-to-end contra el entorno real
├── requirements.txt                            # Para ejecutar scripts/ localmente, fuera de Docker
└── .gitignore
```

> **Nota:** no existe `docker/requirements.txt` ni `.env.example` en la raíz — las dependencias del contenedor de
> Airflow se instalan directamente en `docker/Dockerfile`. `dashboard/` y `mart/` sí tienen su propio
> `requirements.txt`, por ser procesos con dependencias propias (Dash/Flask el primero, SQLAlchemy/psycopg el
> segundo).

## Las tres capas, en detalle

### Capa 1 — Pipeline SIETEL → PostgreSQL (`staging` / `analitico`)

Orquestada por el DAG **`sietel_usuarios_cuentas_pipeline`** (`schedule=None`, disparo manual):

```
aplicar_esquema >> cargar_dimensiones >> obtener_anios_a_cargar
                                              >> cargar_hechos_de_anio.expand(anio=anios)
                                                     >> validar_carga(anios)
```

- **`aplicar_esquema`** ejecuta `sql/01_ddl_postgres.sql` de forma idempotente (`CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`, vistas recreadas con `DROP VIEW IF EXISTS` + `CREATE VIEW` porque
  `CREATE OR REPLACE VIEW` en PostgreSQL solo permite agregar columnas al final, no reordenarlas).
- **`cargar_dimensiones`** versiona `dim_isp` y `dim_permiso_va_agregado` con SCD Tipo 2. Las columnas que disparan una
  nueva versión están explícitamente listadas (`COLUMNAS_VERSIONABLES_ISP`, `COLUMNAS_VERSIONABLES_PERMISO`) —
  **propuesta inicial pendiente de confirmar formalmente con el área de Mercados**, según el propio código.
- **`obtener_anios_a_cargar`** lee la Variable de Airflow `sietel_anios_a_cargar` (`historico`, un año, una lista de
  años separados por coma, o el año en curso por defecto).
- **`cargar_hechos_de_anio`** extrae `dbo.VALineasDedicadas` agregado (`GROUP BY` en SQL Server, nunca detalle crudo),
  **particionado mes a mes** dentro del año — evita agotar memoria/tiempo con un `fetchall()` de hasta 31M+ filas
  brutas, y aprovecha el prefijo `(anio, periodoNumero)` del índice compuesto
  (ver [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)). Cada fila agregada se certifica con
  un hash MD5 (`COLUMNAS_HASH`) antes del `UPSERT`.
- **`validar_carga`** recalcula el mismo agregado desde SQL Server, mes a mes, y compara el hash MD5 fila por fila
  contra lo almacenado — no solo el conteo. También verifica vigencia única en las dimensiones SCD y ausencia de
  duplicados en la vista de consumo.

### Capa 2 — Consolidación y calidad (`capa2` / `calidad`)

Primeras dos tareas del DAG **`sietel_mart_pipeline`**:

1. **`detectar_conflictos_peva`** (`mart/detectar_conflictos_peva.py`) — identifica RUC que amparan más de un
   `peva_codigo` y los clasifica en tres categorías, persistidas en `calidad.conflictos_ruc_peva`:
    - **A — Duplicado por migración de codificación heredada**: mismo `isp_nombre`, un PEVA con el campo `opera` en
      codificación heredada (`SI`/`NO`/`-`), el otro en categórica. **Resolución automática**: se descarta el PEVA con
      codificación heredada.
    - **B — Secuencia del mismo titular**: mismo `isp_nombre`, ambos con codificación categórica, fechas de permiso
      distintas. Requiere verificar si coexisten reportando en el mismo período — **revisión manual**.
    - **C — Nombres distintos bajo el mismo RUC**: sin regla automática posible — **siempre revisión manual**.

   Las columnas de *workflow* (`estado_revision`, `revisado_por`, `notas_revision`, `fecha_revision`) se fijan una sola
   vez y **nunca se sobreescriben** en corridas posteriores del detector — el trabajo humano de revisión no se pierde al
   re-detectar.

2. **`construir_capa2`** (`mart/construir_capa2.py`) — reconstruye por completo
   `capa2.lineas_dedicadas_consolidado`: una serie mensual por cada combinación `(peva, geografía, tipoEnlace,
   tipoCliente, nivelComparticion, portador)`, con relleno **LOCF (last observation carried forward) exclusivamente
   hacia el interior** de la serie de cada PEVA — nunca extrapola hacia meses posteriores al último reporte real. Cada
   fila queda marcada con `es_reportado` / `es_imputado` (mutuamente excluyentes por construcción), y excluye los PEVA
   del Grupo A ya resueltos por el detector de conflictos.

### Capa 3 — Mart analítico (`mart`)

Tercera tarea del DAG: **`aplicar_capa3`** (`mart/aplicar_capa3.py`) aplica `sql/02_ddl_mart.sql` completo (~2.500
líneas) contra PostgreSQL, como `mart_user`, vía el **protocolo simple** de Postgres (conexión `psycopg` cruda en
`autocommit=True`, no SQLAlchemy) — necesario porque el archivo trae su propio `BEGIN;`/`COMMIT;` y no se puede partir
en sentencias individuales del lado del cliente sin arriesgar romper un literal de texto o un bloque `DO $$`.

El archivo, en orden, hace: `DROP SCHEMA mart CASCADE` + `CREATE SCHEMA` (el mart es **completamente reconstruible**
en cada corrida, no incremental) → dimensiones (`dim_periodo`, `dim_prestador`, `dim_geografia`) → tablas puente
(`bridge_geografia_territorio`) → vistas de staging intermedias → tablas de hechos (`fact_lineas_geografia_mes`,
`fact_lineas_velocidad_mes`, `fact_resumen_mercado_mes`, `fact_velocidad_mercado_mes`, `fact_participacion_mercado`,
`fact_ihh_geografico`) → vistas `vw_dashboard_*` de consumo directo del dashboard → **re-otorgamiento explícito de
permisos a `dashboard_lector`** (el `DROP SCHEMA CASCADE` inicial borra cualquier `GRANT` previo, así que el propio
archivo se los devuelve al final, dentro de la misma transacción) → validaciones de integridad (fuera de la transacción,
de solo lectura, pensadas para correrse manualmente tras cada refresco).

**Principio de diseño explícito en todo el archivo**: el cálculo de líneas reportadas, participación de mercado e IHH
usa **exclusivamente `lineas_reportadas`** (dato real) — nunca `total_lineas` (que mezcla real + imputado) para estos
fines. Ver la sección siguiente para el razonamiento completo.

### Dashboard (Dash + Flask-Login)

Aplicación Dash (`dashboard/`), servida con `gunicorn`, con dos páginas:

- **Evolución del mercado** (`pages/evolucion.py`): líneas reportadas y prestadores por mes (barras, no líneas de
  tendencia — un dato faltante se muestra como una caída real, no como una interpolación), tasa de entrega de reportes,
  prestadores que nunca han reportado, composición y diferencia mensual por rango de velocidad.
- **IHH y participación** (`pages/concentracion.py`): evolución histórica del IHH, cobertura del índice, líder de
  mercado, CR2/CR4, participación individual, aporte al IHH por prestador, y evolución de un prestador específico.

**Filtros sincronizados entre páginas** (`dcc.Store` fuera de `dash.page_container`, en `app.py`, para que sobrevivan al
cambio de pestaña):

- `shared-territory`: Nivel geográfico / Provincia / Cantón / Parroquia (`components/territory_filters.py`).
- `shared-filters`: Estado de operación / Prestador (`components/filters_shared.py`).
- El filtro **"Período de participación"** es exclusivo de la página de Concentración — no tiene equivalente en
  Evolución y no se sincroniza.

**Autenticación** (`auth.py`): Flask-Login + bcrypt, con la tabla de usuarios en `auth.usuarios_dashboard` (mismo
PostgreSQL, esquema propio). El guard de sesión se aplica en un `@server.before_request` de Flask —no en un callback de
Dash— así ninguna página se sirve sin sesión válida. Sin autorregistro: altas, bajas y reseteo de contraseña se hacen
exclusivamente vía `dashboard/scripts/gestionar_usuarios.py`, corrido por un administrador con credenciales propias
(nunca con el rol de runtime `dashboard_auth`).

## Principio metodológico: nunca imputar para medir concentración de mercado

Este es el criterio de diseño más importante de todo el sistema, y vale la pena explicarlo una vez, completo:

**El relleno de huecos (LOCF) es aceptable para continuidad visual de una serie de tiempo, pero nunca para medir la
estructura competitiva de un mercado en un mes específico.** Un prestador que deja de reportar tiene una probabilidad
desproporcionadamente alta de estar en crisis, saliendo del mercado, o en incumplimiento — es un caso clásico de dato
faltante *no aleatorio* (MNAR, *missing not at random*, en la terminología de metodología de encuestas). Heredar su
último valor conocido asume implícitamente "sin cambios", cuando estadísticamente es más probable lo contrario. Fabricar
una posición competitiva que no se conoce distorsiona exactamente lo que el índice dice estar midiendo.

Por eso:

- **`fact_lineas_geografia_mes.tiene_reportado`** distingue, para cada prestador y mes, si hubo un reporte real ese mes
  exacto — independientemente de si `capa2` tiene un valor (real o heredado) para ese mes.
- **`fact_participacion_mercado`** calcula `participacion_porcentaje` / `aporte_ihh` **solo** con `lineas_reportadas`
  de quienes tienen `tiene_reportado = TRUE` ese mes. Un prestador sin reporte real queda con esas columnas en
  `NULL` — nunca en `0%` (fabricaría "no tiene mercado") ni con su último valor conocido (fabricaría "sin cambios").
- El **denominador** (`total_lineas_mercado`) se recalcula de forma consistente: es la suma de `lineas_reportadas`
  **solo entre quienes reportaron ese mes**, no el total mezclado con imputados — de lo contrario, todos los prestadores
  quedarían con participación artificialmente baja por igual.
- **`fact_ihh_geografico`** y las vistas `vw_dashboard_ihh` / `vw_dashboard_participacion` exponen columnas de
  **cobertura** (`numero_prestadores_reportaron`, `numero_prestadores_registrados`,
  `porcentaje_cobertura_prestadores`) junto al índice — nunca se publica un IHH sin su contexto de completitud, igual
  que las agencias de estadística oficial (Ofcom, ARCEP, FCC) publican tasas de respuesta junto a sus indicadores.
- **La obligación de reportar de un prestador empieza un año calendario después de la fecha del título habilitante**, no
  el día del otorgamiento — un prestador con título del 15/08/2021 tiene su primer reporte *obligatorio* en agosto de
  2022. `get_reporting_summary` (`dashboard/services/queries.py`) aplica esta regla al calcular la tasa de entrega de
  reportes, para no penalizar a un prestador por meses en los que aún no tenía obligación.
- **Límite reconocido explícitamente**: un prestador con título habilitante otorgado que **jamás** ha entregado un solo
  reporte no aparece en `capa2` ni en `fact_lineas_geografia_mes` (esas tablas se construyen a partir de reportes
  reales). Ese caso —el de incumplimiento total— se hace visible por separado, cruzando contra
  `analitico.v_ultimo_periodo_reportado_detalle` (`mart.vw_prestadores_sin_reportar`, KPI *"Nunca han reportado"* en el
  dashboard, solo disponible a nivel Nacional porque esta fuente no registra geografía para quien nunca reportó).

## Requisitos previos

- Docker (Compose v2) sobre el host/VM donde corre este pipeline.
- Acceso de red al servidor SQL Server de SIETEL (puerto 1433).
- Instancia PostgreSQL accesible para: metadata de Airflow, la base analítica `sietel_analitico`, y el dashboard (puede
  ser la misma instancia, distintas bases o distintos esquemas — así está desplegado hoy).
- Usuario de SQL Server con permiso de `SELECT` sobre `dbo.VALineasDedicadas`, `dbo.ISP`, `dbo.PermisoVAgregado`,
  `dbo.Parroquia`, `dbo.Ciudad`, `dbo.Provincia`.
- Ventana de mantenimiento formal y acceso del DBA de SIETEL para modificar índices en el servidor de producción (ver
  [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)).

## Roles y permisos de PostgreSQL

Ningún rol de aplicación es dueño de más de lo que necesita. Todos se crean **por línea de comandos, directamente en la
VM** (documentado en *"Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx"*) — los archivos SQL de este
repositorio **asumen que el rol ya existe** y fallan con un error explícito si no es así, en vez de crearlo
silenciosamente con una contraseña provisional.

| Rol                | Dueño de / acceso a                                                                                     | Usado por                                                    |
|--------------------|---------------------------------------------------------------------------------------------------------|--------------------------------------------------------------|
| `sietel_user`      | Esquemas `staging` y `analitico` (Capa 1)                                                               | Capa 1 (`scripts/*.py`)                                      |
| `mgonzalez`        | Lectura de `analitico`                                                                                  | Consumo externo histórico (Power BI)                         |
| `mart_user`        | Esquemas `capa2`, `mart`, `calidad` (dueño)                                                             | `mart/*.py`, `sql/02_ddl_mart.sql`, `sql/04_ddl_calidad.sql` |
| `dashboard_lector` | `SELECT` únicamente sobre `mart.*`                                                                      | Dashboard, lectura analítica                                 |
| `dashboard_auth`   | `SELECT`/`INSERT`/`UPDATE` únicamente sobre `auth.usuarios_dashboard`                                   | Dashboard, login/sesión                                      |
| `calidad_lector`   | `SELECT` sobre `calidad.*`                                                                              | Futuro dashboard de consistencia de datos                    |
| `calidad_revisor`  | `SELECT` sobre `calidad.*` + `UPDATE` solo de las columnas de workflow en `calidad.conflictos_ruc_peva` | Revisión manual de conflictos RUC/PEVA                       |

**Por qué `dashboard_lector` y `dashboard_auth` son roles separados, no uno solo con ambos permisos**: el dashboard
necesita leer `mart.*` pero también escribir en la tabla de usuarios. Un solo rol con ambos permisos amplía la
superficie de ataque en las dos direcciones; con roles separados, comprometer la sesión de lectura analítica no da
acceso a usuarios, y viceversa.

**`ALTER DEFAULT PRIVILEGES FOR ROLE mart_user`** en `sql/03_ddl_auth.sql` y `sql/04_ddl_calidad.sql` es lo que hace que
`dashboard_lector`/`calidad_lector` sigan teniendo acceso después de que `aplicar_capa3.py` haga
`DROP SCHEMA ... CASCADE` y recree todo — sin esto, cada refresco del mart dejaría el dashboard sin permisos.

Orden de aplicación de los scripts de rol/permiso (una sola vez, antes del primer `aplicar_capa3`):

```
sql/00_roles_mart.sql   # requiere que mart_user ya exista
sql/03_ddl_auth.sql     # requiere que mart_user, dashboard_lector, dashboard_auth ya existan
sql/04_ddl_calidad.sql  # requiere que mart_user, calidad_lector, calidad_revisor ya existan
```

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

`ANIO_INICIO_HISTORICO` (2011) y `ANIO_FIN_HISTORICO` (2025) se definen **únicamente** en `scripts/config.py` — no se
redefinen en ningún DAG ni script, para evitar la divergencia entre copias que ya ocurrió antes.

### Capa 2/3 (`mart/.env`)

| Variable                                                            | Descripción                              |
|---------------------------------------------------------------------|------------------------------------------|
| `MART_USER_USER` / `MART_USER_PASSWORD`                             | Credenciales de `mart_user`              |
| `ANALITICO_PG_HOST` / `ANALITICO_PG_PORT` / `ANALITICO_PG_DATABASE` | Misma instancia PostgreSQL que la Capa 1 |
| `LOG_LEVEL`                                                         | Default `INFO`                           |

### Airflow (`docker/docker-compose.yml`)

Variables propias de Airflow, inyectadas por entorno: `AIRFLOW__CORE__FERNET_KEY`, `AIRFLOW__API_AUTH__JWT_SECRET`,
`_AIRFLOW_WWW_USER_USERNAME`, y credenciales `AIRFLOW_METADATA_PG_*` de la base de metadata bare-metal. Además, todas
las variables de Capa 1 y `MART_USER_USER`/`MART_USER_PASSWORD` de Capa 2/3, para que los DAGs puedan ejecutarse dentro
del contenedor.

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

`dashboard/config.py` falla explícito si falta cualquiera de estas variables — no existe la opción de conectar con una
contraseña vacía.

## Puesta en marcha, paso a paso

1. **Crear los roles de PostgreSQL** por línea de comandos (`mart_user`, `dashboard_lector`, `dashboard_auth`,
   `calidad_lector`, `calidad_revisor`) — ver *"Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx"*.
2. **Aplicar permisos base**, en este orden exacto: `sql/00_roles_mart.sql` → `sql/03_ddl_auth.sql` →
   `sql/04_ddl_calidad.sql`.
3. **Otorgar a `mart_user` lectura sobre `analitico`** (ejecutar como `sietel_user` o superusuario, ver comentario en
   `sql/04_ddl_calidad.sql`):
   ```sql
   GRANT USAGE ON SCHEMA analitico TO mart_user;
   GRANT SELECT ON analitico.v_ultimo_periodo_reportado_detalle TO mart_user;
   GRANT SELECT ON analitico.v_lineas_dedicadas_resumen TO mart_user;
   ```
4. **Levantar Airflow**: `docker compose -f docker/docker-compose.yml up -d` (requiere la base de metadata ya creada en
   PostgreSQL bare-metal).
5. **Correr `sietel_usuarios_cuentas_pipeline`** (Capa 1) al menos una vez, para poblar `staging`/`analitico`.
6. **Correr `sietel_mart_pipeline`** (Capa 2/3) — reconstruye `calidad`, `capa2` y `mart` desde cero.
7. **Crear el primer usuario del dashboard**:
   ```bash
   cd dashboard/scripts
   python gestionar_usuarios.py crear --username jperez --nombre "Juan Pérez"
   ```
8. **Levantar el dashboard**: `docker compose -f dashboard/docker/docker-compose.yml up -d --build`, disponible en el
   puerto `8050`.

## Uso diario

### Vía Airflow (recomendado)

**Capa 1** — Airflow UI → **Admin → Variables** → `sietel_anios_a_cargar`:

| Valor                            | Comportamiento                                                        |
|----------------------------------|-----------------------------------------------------------------------|
| `historico`                      | Carga el rango completo `ANIO_INICIO_HISTORICO`..`ANIO_FIN_HISTORICO` |
| `2025`                           | Carga solo ese año                                                    |
| `2023,2024,2025`                 | Carga esa lista de años                                               |
| (ausente o cualquier otro valor) | Carga solo el año en curso                                            |

Luego, **DAGs** → `sietel_usuarios_cuentas_pipeline` → *Trigger DAG* (`schedule=None`: siempre manual).

**Capa 2/3** — **DAGs** → `sietel_mart_pipeline` → *Trigger DAG*, después de cada actualización relevante de Capa 1, o
cuando se necesite refrescar el dashboard.

### Vía CLI (pruebas puntuales / smoke tests)

```bash
# Capa 1 — aplicar esquema y cargar dimensiones (primera vez)
python scripts/aplicar_esquema.py
python scripts/cargar_dimensiones.py

# Capa 1 — cargar un año completo (itera los 12 meses internamente)
python scripts/cargar_hechos_anio.py --anio 2025

# Capa 1 — cargar un solo mes (smoke test, con desglose de tiempos SQL Server vs Postgres)
python scripts/cargar_hechos_anio.py --anio 2025 --mes 12

# Capa 1 — certificación cruzada de uno o más años
python scripts/validar_carga.py --anios 2025

# Capa 1 — backfill de códigos administrativos (años cargados antes del 22-jul-2026)
python scripts/sincronizar_codigos_administrativos.py

# Capa 2/3 — reconstruir todo el mart manualmente
cd mart
python detectar_conflictos_peva.py
python construir_capa2.py
python aplicar_capa3.py

# Dashboard — administración de usuarios
cd dashboard/scripts
python gestionar_usuarios.py listar
python gestionar_usuarios.py desactivar --username jperez
python gestionar_usuarios.py resetear-password --username jperez
```

## Modelo de datos

**Esquema `staging`** (Capa 1, tablas físicas):

| Tabla                         | Contenido                                                                                                                             |
|-------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `va_lineas_dedicadas_resumen` | Hechos agregados: una fila por `(peva_codigo, par_codigo, periodoNumero, anio, tipoEnlace, tipoCliente, nivelComparticion, portador)` |
| `dim_isp`                     | Dimensión ISP, versionada (SCD Tipo 2)                                                                                                |
| `dim_permiso_va_agregado`     | Dimensión de permisos de prestador, versionada (SCD Tipo 2)                                                                           |
| `control_cargas`              | Auditoría de cada corrida: tipo, año, filas, estado, errores                                                                          |
| `historial_correcciones`      | Snapshot (JSONB) de cada fila cuya certificación de contenido cambió entre cargas                                                     |

**Esquema `analitico`** (Capa 1, vistas de consumo):

| Vista                                | Uso                                                                                                                                                                                                                                         |
|--------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `v_lineas_dedicadas_resumen`         | Serie histórica completa, dimensiones resueltas por vigencia temporal. Solo prestadores con actividad reportada                                                                                                                             |
| `v_ultimo_periodo_reportado_detalle` | Último período reportado por cada prestador vigente + estado administrativo. Incluye prestadores sin ningún reporte (`tiene_reportes = false`), vía `LEFT JOIN` — es la única fuente de este proyecto que conoce a quien nunca ha reportado |

**Esquema `calidad`** (Capa 2):

| Objeto                | Contenido                                                                                    |
|-----------------------|----------------------------------------------------------------------------------------------|
| `conflictos_ruc_peva` | RUC con múltiples PEVA en conflicto, clasificados (A/B/C) + workflow de revisión persistente |
| `vw_pevas_excluidos`  | PEVA del Grupo A confirmados, que `construir_capa2.py` excluye de la serie consolidada       |

**Esquema `capa2`** (Capa 2):

| Tabla                          | Contenido                                                                                                                                                        |
|--------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `lineas_dedicadas_consolidado` | Serie mensual completa por PEVA/geografía/tipoEnlace/tipoCliente/nivelComparticion/portador, con relleno LOCF solo interior y flags `es_reportado`/`es_imputado` |

**Esquema `mart`** (Capa 3 — el más grande, ~2.500 líneas de DDL): dimensiones (`dim_periodo`, `dim_prestador`,
`dim_geografia`), tabla puente `bridge_geografia_territorio`, tablas de hechos (`fact_lineas_geografia_mes`,
`fact_lineas_velocidad_mes`, `fact_resumen_mercado_mes`, `fact_velocidad_mercado_mes`,
`fact_participacion_mercado`, `fact_ihh_geografico`), la vista `vw_prestadores_sin_reportar`, y las vistas
`vw_dashboard_*` que consume directamente el dashboard (`vw_dashboard_evolucion`, `vw_dashboard_velocidades`,
`vw_dashboard_participacion`, `vw_dashboard_ihh`, `vw_dashboard_filtros_geograficos`).

**Columnas por rango de velocidad** (`lineas_dl_*` para bajada, `lineas_ul_*` para subida) cuentan **líneas/cuentas**,
no usuarios finales — para usuarios finales usar `total_usuarios`:

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

Desde el 22-jul-2026, `va_lineas_dedicadas_resumen` incluye `codigo_provincia`, `codigo_ciudad` y `codigo_parroquia`
(VARCHAR, no INTEGER, para preservar ceros a la izquierda como `"01"` o `"0801"`), tomados de
`Provincia.codigo`/`Ciudad.codigoCiudad`/`Parroquia.codigoParroquia` en SQL Server, para cruce con las tablas del INEC.
**No forman parte de `COLUMNAS_HASH`**: son metadata derivada de `par_codigo` (jerarquía administrativa fija), no parte
de la llave natural ni de las métricas medidas.

Los años cargados **antes** de este cambio necesitan un backfill puntual —
`scripts/sincronizar_codigos_administrativos.py` trae el mapeo `par_codigo → códigos` una sola vez (tabla pequeña, no
requiere volver a agregar `VALineasDedicadas`) y actualiza las filas existentes. Es idempotente y reutilizable; no está
cableado al DAG, se invoca por CLI bajo demanda. Los años cargados **después** del cambio ya traen los códigos desde el
primer INSERT.

Este backfill **no** modifica `hash_contenido` ni genera entradas en `historial_correcciones` — no es una corrección de
contenido certificado, es completar metadata administrativa.

## Historial de correcciones

`staging.historial_correcciones`, poblada por el trigger `trg_registrar_correccion_resumen` (`BEFORE UPDATE` sobre
`va_lineas_dedicadas_resumen`), registra un snapshot completo (JSONB) de la fila anterior cada vez que
`hash_contenido` cambia entre una carga y otra — sin importar qué script disparó el `UPDATE`.

**Importante:** esta tabla no distingue una corrección real de un prestador (cambió su reporte de un período ya cerrado)
de un reprocesamiento propio (se corrigió un bug de fórmula y se recargó el año) — ambos casos generan una entrada. Esa
distinción de causa vive en `staging.control_cargas` y en el historial de Git, no en esta tabla.

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

`validar_carga.py` recalcula el agregado completo desde SQL Server —mes a mes, igual que la carga— y compara un hash MD5
por fila contra lo almacenado en PostgreSQL, certificando que el **valor** de cada fila migrada coincide con el origen,
no solo la cantidad de filas. Chequeos adicionales en la misma tarea: dimensiones SCD sin versiones vigentes duplicadas,
y vista de consumo sin filas duplicadas por el `JOIN` de vigencia temporal (verificado agrupando por la llave natural
completa de 8 columnas). El resultado se imprime como reporte consolidado (✅/❌ por chequeo) y se registra en
`staging.control_cargas`.

`sql/02_ddl_mart.sql` incluye su propio bloque de validaciones (sección 17 del archivo, fuera de la transacción
principal), incluyendo invariantes específicas de la corrección de metodología de datos reales: ningún prestador sin
reporte real ese mes debe tener `participacion_porcentaje`/`aporte_ihh` distinto de `NULL`, la cobertura de prestadores
siempre entre 0 y 100, y `CR2 ≤ CR4 ≤ 100`.

## Calidad de datos conocida

- **Patrón append-only sin deduplicación**: la misma línea genera una fila nueva cada mes aunque no cambie nada —
  verificado con un caso que aparece 4.843 veces entre 2015-2024 en la misma dirección. El pipeline **no deduplica**
  silenciosamente (sería alterar el dato oficial reportado sin intervención de SIETEL o del prestador); una vista de
  auditoría de duplicados queda pendiente como mejora futura, separada del dato certificado.
- **Campo `opera` con codificación heredada inconsistente**: la mayoría de permisos usa categorías descriptivas
  (`Opera Normalmente`, `Nuevo`, `Cancelación`, etc.), pero un subconjunto usa una codificación antigua (`SI`/`NO`/
  `-`) — consistente con captura residual nunca actualizada. Esta codificación heredada resultó ser la causa de la
  mayoría de los conflictos de "RUC con múltiples PEVA" (Grupo A, resuelto automáticamente).
- **Cadencia de reporte no uniforme entre prestadores**: confirmado con datos reales que un prestador grande puede
  reportar trimestralmente en vez de mensualmente durante períodos extensos de su historia — el patrón de "picos" en
  gráficas de evolución no es un error del pipeline, es la cadencia real de reporte reflejada fielmente por el relleno
  LOCF solo interior.
- **`v_ultimo_periodo_reportado_detalle` no tiene geografía para prestadores sin reportes**: SIETEL solo conoce la
  ubicación de un prestador a través de su reporte real (`VALineasDedicadas` especifica parroquia); si nunca reportó, no
  hay forma de saberlo. El KPI *"Nunca han reportado"* del dashboard solo está disponible a nivel Nacional por esta
  razón estructural, no por una limitación de la consulta.
- **Lista de columnas versionables SCD no cerrada formalmente**: `COLUMNAS_VERSIONABLES_ISP` y
  `COLUMNAS_VERSIONABLES_PERMISO` en `cargar_dimensiones.py` son, según el propio código, una propuesta inicial
  pendiente de confirmar con el área de Mercados.
- **RUC con múltiples PEVA de nombre distinto (Grupo C)**: sin resolución automática posible — queda en cola de revisión
  manual en `calidad.conflictos_ruc_peva`.

## Seguridad del dashboard

- Sesión de Flask-Login, cookies firmadas con `SECRET_KEY` propio (nunca en Git, generado con `secrets.token_hex`).
- Contraseñas con `bcrypt`, nunca texto plano.
- Sin autorregistro — toda gestión de usuarios pasa por `dashboard/scripts/gestionar_usuarios.py`, ejecutado con
  credenciales administrativas separadas del rol de runtime.
- El guard de autenticación (`@server.before_request`) bloquea **todas** las rutas salvo `/login`, `/logout` y los
  endpoints internos de Dash (`/assets`, `/_dash-*`) — se aplica antes de que Dash sirva cualquier layout, no después.
- Mismo mensaje de error para usuario inexistente, contraseña incorrecta o usuario inactivo — no revela cuál de las tres
  cosas falló.
- `APP_DEBUG=false` obligatorio en producción — el modo debug de Flask junto a sesiones autenticadas sería un riesgo de
  seguridad serio, no cosmético.
- Servido con `gunicorn`, nunca con el servidor de desarrollo de Flask/Dash.

## Pruebas de integración

`tests/verificar_pipeline.py` no es una suite de unit tests con mocks — valida contra el entorno real:

```bash
python tests/verificar_pipeline.py --anios 2026
python tests/verificar_pipeline.py --anios 2024 2025 2026 --verbose
```

Verifica, en orden: conectividad a ambas bases, existencia de las tablas/vistas esperadas del esquema de Capa 1, y
delega la certificación cruzada en `validar_carga.validar_anios()` (la misma función que corre en la tarea del DAG).

> **Cobertura conocida como incompleta:** las listas `TABLAS_ESPERADAS` y `VISTAS_ESPERADAS` de este script no
> incluyen `staging.historial_correcciones` ni `analitico.v_ultimo_periodo_reportado_detalle`, ni ningún objeto del
> esquema `mart` (Capa 2/3) todavía.

## Documentación relacionada

| Documento                                                           | Contenido                                                               |
|---------------------------------------------------------------------|-------------------------------------------------------------------------|
| `Informe_Hallazgos_SIETEL.docx`                                     | Por qué se descartó `VAReporteUsuariosCuentas`, patrón append-only      |
| `Propuesta_Modificacion_SIETEL.pptx`                                | Propuesta de correcciones estructurales para el equipo de SIETEL        |
| `Especificacion_Tecnica_SIETEL.docx`                                | Diseño SCD Tipo 2, lógica de carga, plan de migración                   |
| `Instruccion_Tecnica_Indice_SIETEL_v1.3.docx`                       | Script de índice listo para el DBA de producción                        |
| *Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx* | Fuente de verdad de qué roles de PostgreSQL existen y cuándo se crearon |

Patrones de diseño (certificación de contenido vía hash, carga por lotes con `execute_batch`) tomados como referencia
de [`Zerausir/samm_pipeline`](https://github.com/Zerausir/samm_pipeline), un pipeline hermano con el que se comparte
infraestructura de VMs y versión de Airflow.

## Hoja de ruta / pendientes

- [ ] Aplicar el índice `IX_VALineasDedicadas_Analitico` en el servidor de producción de SIETEL.
- [ ] Vista de auditoría de líneas potencialmente duplicadas (separada del dato certificado).
- [ ] Cerrar formalmente con el área de Mercados la lista de columnas versionables SCD de ISP y PermisoVAgregado.
- [ ] Ampliar `tests/verificar_pipeline.py` para cubrir `historial_correcciones`, `v_ultimo_periodo_reportado_detalle`
  y los objetos del esquema `mart`.
- [ ] Documentar formalmente las variables `AIRFLOW_METADATA_PG_*` en un archivo de referencia de configuración.
- [ ] Selección múltiple en Provincia/Cantón/Parroquia del dashboard (hoy es selección única, sincronizada entre
  páginas — extender a multi-selección requiere rediseñar `components/territory_filters.py` y las consultas que dependen
  de un solo `territorio_id`).
- [ ] Extender los filtros de Estado de operación / Prestador a las gráficas de velocidad de la página de Evolución.
- [ ] Incorporar datos de internet móvil (fuente aún no identificada en SIETEL).
- [ ] Análisis geoespacial cruzando `par_codigo` con datos de sectores censales.
- [ ] Pantalla de consistencia de datos sobre `calidad.conflictos_ruc_peva` (Grupos B/C pendientes de revisión manual).

## Dónde obtener ayuda

Para dudas sobre este proyecto (pipeline o dashboard), contactar al equipo de analítica de la Dirección de Mercados.
Para problemas de acceso o desempeño del propio SIETEL, canalizar a través de `Propuesta_Modificacion_SIETEL.pptx` y el
equipo técnico de SIETEL.

## Mantenedores

- **Marcos González Auhing** — Dirección de Mercados, ARCOTEL.
- **Iván Suárez Fabara** — Dirección de Mercados, ARCOTEL.