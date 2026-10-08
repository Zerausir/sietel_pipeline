# OBTEL — Observatorio de Telecomunicaciones

Plataforma de datos de extremo a extremo de la **Dirección de Mercados de ARCOTEL**. Extrae, certifica, modela y
publica en un dashboard web propio la información que los prestadores de servicios de telecomunicaciones reportan al
regulador en **SIETEL** (SQL Server). Sirve de insumo para el análisis de mercado y para el control regulatorio del
sector.

[![Apache Airflow](https://img.shields.io/badge/Apache%20Airflow-3.3.0-017CEE?logo=apacheairflow&logoColor=white)](https://airflow.apache.org/)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![SQL Server](https://img.shields.io/badge/SQL%20Server-ODBC%20Driver%2018-CC2927?logo=microsoftsqlserver&logoColor=white)](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
[![Dash](https://img.shields.io/badge/Dash-4.4.1-008DE4?logo=plotly&logoColor=white)](https://dash.plotly.com/)
[![Docker Compose](https://img.shields.io/badge/Docker%20Compose-v2-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

---

## Tabla de contenidos

1. [Descripción general](#1-descripción-general)
2. [Motivación](#2-motivación)
3. [Arquitectura](#3-arquitectura)
4. [Estructura del repositorio](#4-estructura-del-repositorio)
5. [Pipeline de datos](#5-pipeline-de-datos)
6. [Principio metodológico: nunca imputar](#6-principio-metodológico-nunca-imputar)
7. [Geografía de nodos ISP](#7-geografía-de-nodos-isp)
8. [Dashboard](#8-dashboard)
9. [Modelo de datos](#9-modelo-de-datos)
10. [Requisitos](#10-requisitos)
11. [Instalación y puesta en marcha](#11-instalación-y-puesta-en-marcha)
12. [Configuración](#12-configuración)
13. [Operación](#13-operación)
14. [Validación y calidad de datos](#14-validación-y-calidad-de-datos)
15. [Pruebas](#15-pruebas)
16. [Solución de problemas](#16-solución-de-problemas)
17. [Registro de cambios relevantes](#17-registro-de-cambios-relevantes)
18. [Hoja de ruta](#18-hoja-de-ruta)
19. [Documentación relacionada](#19-documentación-relacionada)
20. [Contribución](#20-contribución)
21. [Mantenedores y soporte](#21-mantenedores-y-soporte)
22. [Licencia](#22-licencia)

---

## 1. Descripción general

OBTEL cubre dos servicios regulados, cada uno con su propio módulo en el dashboard:

| Módulo                                           | Fuente                                                                  | Contenido                                                                                                             |
|--------------------------------------------------|-------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| **SAI** — Servicio de Acceso a Internet (`/sai`) | SIETEL (SQL Server) → `sietel_analitico` (PostgreSQL), este repositorio | Líneas dedicadas de internet fijo, concentración de mercado, cumplimiento de reporte, geografía de nodos ISP, calidad de datos maestros |
| **SMA** — Servicio Móvil Avanzado (`/sma`)       | `samm_db` (PostgreSQL), poblada por [`samm_pipeline`](https://github.com/Zerausir/samm_pipeline) | Calidad de datos móviles (mediciones de campo). Este repositorio solo aporta las páginas del dashboard           |

Capacidades principales del módulo SAI:

- **Extracción agregada en origen.** `dbo.VALineasDedicadas` se agrega dentro de SQL Server; el detalle crudo nunca
  sale de SIETEL.
- **Certificación de contenido.** Cada carga se compara con el origen mediante un hash MD5 por fila: no solo coincide
  la cantidad de filas, coincide el valor de cada una.
- **Historia de dimensiones.** `ISP`, `PermisoVAgregado` y `NodoISP` se versionan con SCD Tipo 2, así se puede
  reconstruir el estado de un prestador en cualquier punto del histórico aunque SIETEL solo guarde el estado actual.
- **Actualización automática.** Un detector diario compara una huella de SIETEL por año y mes y recarga solo los meses
  que cambiaron.
- **Nunca imputa.** Toda cifra es exactamente lo reportado. La falta de reporte se mide con un panel de obligación y se
  publica como cobertura junto a cada total e índice.
- **Concentración de mercado.** IHH, CR2, CR4 y participación, calculados solo sobre datos reportados.
- **Calidad de datos maestros.** Detección de RUC con varios PEVA en conflicto y de nodos cuya ubicación reportada no
  coincide con su coordenada (cruce contra la cartografía oficial de CONALI).
- **Control regulatorio.** Prestadores que nunca reportaron, que dejaron de reportar o con variaciones anómalas, y
  priorización de a quién exigir la carga.
- **Títulos habilitantes (SIGER_V3).** Réplica certificada de los títulos habilitantes, concesionarios y facturación
  de espectro de SIGER, y cruce de los titulares SAI vigentes con los prestadores de OBTEL (ver
  [5.4](#54-siger_v3--siger_pipeline)).

## 2. Motivación

- **La tabla resumen de SIETEL no es auditable.** `dbo.VAReporteUsuariosCuentas` resume en teoría las líneas
  dedicadas, pero es una tabla física sin vista, trigger ni procedimiento que explique cómo se puebla: sus
  inconsistencias no son trazables al origen (ver `Informe_Hallazgos_SIETEL.docx`). `dbo.VALineasDedicadas` sí es un
  dato crudo auditable: una fila por línea, por cliente y por período, reportada directamente por el prestador.
- **SIETEL no verifica la ubicación de los nodos.** `dbo.Parroquia` usa una codificación administrativa antigua y nunca
  se había contrastado con una fuente cartográfica independiente.
- **Las inconsistencias de control estaban dispersas.** Quién nunca reportó, quién dejó de hacerlo y quién cambió
  drásticamente lo que reporta existían como piezas sueltas, no como un módulo con filtros propios.
- **Independencia de Power BI para el día a día.** El dashboard propio permite a la Dirección de Mercados trabajar con
  datos certificados y con la metodología documentada aquí.

## 3. Arquitectura

### 3.1 Flujo de datos

```
┌───────────────────── SIETEL — SQL Server (172.20.1.38) ─────────────────────┐
│ VALineasDedicadas · VAFormularioLineasDedicadas · ISP · PermisoVAgregado ·  │
│ NodoISP · Parroquia · Ciudad · Provincia                                    │
└─────────────────────────────────────────────────────────────────────────────┘
        │  pyodbc + ODBC Driver 18 (solo lectura)
        ▼
┌───────────── DAG sietel_detector_cambios (diario, 06:00) ──────────────┐
│ Huella por (año, mes) vs staging.huella_fuente → meses con cambios     │
└────────────────────────────────────────────────────────────────────────┘
        │  dispara con conf {"periodos": [[año, mes], ...]}
        ▼
┌───────────── CAPA 1 — DAG sietel_usuarios_cuentas_pipeline ────────────┐
│ esquema → dimensiones SCD2 → nodos ISP → formularios →                 │
│ hechos por mes (mapeado por año) → validación cruzada → huella         │
│ Destino: PostgreSQL sietel_analitico — esquemas staging y analitico    │
└────────────────────────────────────────────────────────────────────────┘
        │  dispara al terminar
        ▼
┌───────────── CAPAS 2 y 3 — DAG sietel_mart_pipeline ───────────────────┐
│ calidad → conflictos RUC/PEVA → capa2 → geografía de nodos → mart      │
│ Destino: esquemas calidad, capa2 y mart (reconstrucción completa)      │
└────────────────────────────────────────────────────────────────────────┘
        │  rol de solo lectura dashboard_lector
        ▼
┌───────────── DASHBOARD OBTEL — Dash + gunicorn ────────────────────────┐
│ SAI: Evolución · IHH y participación · Mapa de nodos · Discrepancias · │
│      Control · Conflictos RUC/PEVA · Prioridad de carga                │
│ SMA: Calidad de Datos móviles · Calidad de Voz (pausada)  ← samm_db    │
└────────────────────────────────────────────────────────────────────────┘
```

Los reportes existentes de Power BI siguen leyendo `analitico` con su propio rol (`mgonzalez`).

### 3.2 Infraestructura

| Componente            | Ubicación                        | Detalle                                                                                  |
|-----------------------|----------------------------------|------------------------------------------------------------------------------------------|
| SIETEL                | SQL Server `172.20.1.38:1433`    | Base `SIETEL`. Fuente de verdad; OBTEL solo lee                                          |
| SIGER_V3              | SQL Server `192.168.129.40`      | Base `SIGER_V3` (SQL Server 2012 SP2). Títulos habilitantes y facturación de espectro; solo lectura, permisos por columna |
| PostgreSQL            | VM1 `192.168.129.50:5432`        | Bases `sietel_analitico` (este proyecto), `samm_db` (SMA) y la metadata de Airflow       |
| Airflow               | VM2, `docker/docker-compose.yml` | LocalExecutor; interfaz web en el puerto `8081` (el `8080` lo usa `samm_pipeline`)        |
| Dashboard             | VM2, `dashboard/docker/`         | Contenedor `sietel_dashboard`, puerto `8050`                                              |

### 3.3 Decisiones técnicas

| Decisión                                                    | Motivo                                                                                                                                                                                                                |
|-------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `pyodbc` y no `pymssql`                                     | SIETEL exige una negociación TLS que FreeTDS (base de `pymssql`) rechaza (`login packet rejected`, confirmado con TDSDUMP). El driver ODBC de Microsoft sí negocia                                                     |
| `UnsafeLegacyRenegotiation` en OpenSSL                      | SQL Server 2008 R2 no soporta RFC 5746, que OpenSSL 3 exige por defecto. Se aplica solo en `docker/Dockerfile`, nunca en un contenedor compartido                                                                     |
| `TrustServerCertificate=yes`                                | El certificado de SIETEL no es verificable desde el contenedor. El canal va cifrado, pero no protege contra suplantación del servidor en la red interna. Riesgo aceptado y documentado en `scripts/config.py`           |
| Agregación dentro de SQL Server, mes a mes                  | Aprovecha el prefijo `(anio, periodoNumero)` del índice de producción, acota un fallo a un mes y limita la memoria por consulta                                                                                       |
| `capa2` como tablas físicas reconstruidas                   | La consolidación de PEVA y el cruce punto-en-polígono serían inviables de recalcular en cada consulta del dashboard                                                                                                   |
| `mart` reconstruido completo en cada corrida                | Varios cálculos dependen de toda la historia (primer y último reporte de cada prestador, cobertura, "reporte detenido", `LAG()` del dashboard). Una actualización parcial daría resultados incorrectos                  |
| Geoprocesamiento con `shapely` y no PostGIS                 | La instancia PostgreSQL no tiene extensiones geoespaciales. La geometría se guarda como GeoJSON en `JSONB`, mismo patrón que `samm_pipeline`                                                                          |
| Un rol de PostgreSQL por consumidor                         | Revocar o diagnosticar un acceso afecta solo a ese consumidor (ver [Roles](#113-roles-y-permisos-de-postgresql))                                                                                                     |

## 4. Estructura del repositorio

```
sietel_pipeline/
├── dags/                                       # Orquestación (Airflow)
│   ├── sietel_detector_cambios.py              # Diario: detecta meses nuevos o corregidos y dispara la carga
│   ├── sietel_usuarios_cuentas_pipeline.py     # Capa 1: SIETEL → staging / analitico
│   ├── sietel_mart_pipeline.py                 # Capas 2 y 3: calidad → capa2 → geografía de nodos → mart
│   └── siger_pipeline.py                       # Diario 02:00: SIGER_V3 → siger, validación y cruce con OBTEL
├── scripts/                                    # Capa 1
│   ├── config.py                               # Conexiones y ANIO_INICIO_HISTORICO / ANIO_FIN_HISTORICO
│   ├── aplicar_esquema.py                      # Aplica sql/01_ddl_postgres.sql (idempotente)
│   ├── cargar_dimensiones.py                   # SCD2: dim_isp y dim_permiso_va_agregado
│   ├── cargar_nodo_isp.py                      # SCD2: dim_nodo_isp (con códigos INEC)
│   ├── cargar_formularios_lineas.py            # Snapshot de VAFormularioLineasDedicadas ("sin servicio")
│   ├── cargar_hechos_anio.py                   # Hechos agregados por mes, upsert certificado por hash
│   ├── validar_carga.py                        # Certificación cruzada SQL Server vs PostgreSQL
│   ├── detectar_cambios.py                     # Huella de SIETEL por (año, mes) vs staging.huella_fuente
│   ├── sincronizar_codigos_administrativos.py  # Backfill de códigos INEC (fuera del DAG)
│   └── remediar_versiones_espurias_scd2.py     # Remediación puntual de versiones SCD2 espurias
├── mart/                                       # Capas 2 y 3
│   ├── aplicar_capa3.py                        # Aplica sql/04_ddl_calidad.sql y sql/02_ddl_mart.sql
│   ├── detectar_conflictos_peva.py             # Clasifica RUC con varios PEVA (A/B/C)
│   ├── construir_capa2.py                      # capa2.lineas_dedicadas_consolidado (solo lo reportado)
│   ├── limpiar_coordenadas_nodo_isp.py         # Coordenadas DMS → decimal, validación de rango
│   ├── cargar_parroquias.py                    # Shapefile CONALI → geometría por parroquia/cantón/provincia
│   ├── detectar_discrepancias_geografia_nodo.py# Cruce punto-en-polígono, discrepancias por cantón
│   ├── data/shapefiles/parroquial/             # Shapefile CONALI (fuera de Git, ver su README)
│   └── requirements.txt
├── siger/                                      # SIGER_V3 (ver sección 5.4)
│   ├── config_siger.py                         # Conexiones SIGER_*, columnas permitidas, universo SAI, umbrales
│   ├── probar_conexion.py                      # Prueba de conectividad y permisos (solo lectura)
│   ├── aplicar_esquema_siger.py                # Aplica sql/12_ddl_siger.sql como siger_user
│   ├── cargar_siger.py                         # Snapshot por reemplazo, certificado antes del COMMIT
│   ├── huella_siger.py                         # Huella por tabla vs siger.huella_fuente: recarga solo si cambió
│   ├── validar_siger.py                        # Certificación cruzada en ambas direcciones + accesos LOPDP
│   ├── construir_cruce_obtel.py                # calidad.hallazgos_siger_obtel (como mart_user)
│   ├── reglas.py                               # contrato_key, RUC resuelto, tipo_enlace
│   └── hash_siger.py                           # Hash MD5 por fila, igual en pyodbc y psycopg2
├── sql/
│   ├── 00_roles_mart.sql                       # Permisos de mart_user
│   ├── 01_ddl_postgres.sql                     # DDL Capa 1: staging y analitico
│   ├── 02_ddl_mart.sql                         # DDL Capa 3: mart completo + invariantes bloqueantes
│   ├── 03_ddl_auth.sql                         # Esquema auth (login del dashboard)
│   ├── 04_ddl_calidad.sql                      # Esquema calidad (conflictos y discrepancias)
│   ├── 05_roles_eda.sql                        # Rol de solo lectura eda_lector
│   ├── 06…10_patch_*.sql                       # Parches puntuales ya incorporados (ver sección 17)
│   ├── 11_roles_siger.sql                      # Rol siger_user y esquema siger (solo documentación, no re-ejecutar)
│   ├── 12_ddl_siger.sql                        # DDL siger: réplica cruda, vistas SAI, permisos LOPDP
│   └── 13_ddl_calidad_siger.sql                # calidad.hallazgos_siger_obtel
├── dashboard/                                  # Aplicación web OBTEL
│   ├── app.py                                  # Layout raíz, stores compartidos, caché, navegación
│   ├── auth.py                                 # Flask-Login + bcrypt, /login y /logout
│   ├── config.py                               # Configuración por variables de entorno
│   ├── extensions.py                           # Instancia compartida de Flask-Caching
│   ├── pages/                                  # Una página Dash por módulo (ver sección 8)
│   ├── components/                             # UI común y familias de filtros
│   ├── services/
│   │   ├── database.py                         # Engines SQLAlchemy (mart, auth, SMA)
│   │   ├── queries.py                          # Consultas cacheadas contra mart.*
│   │   ├── queries_sma.py                      # Consultas del módulo SMA (samm_db)
│   │   └── cache_mart.py                       # Vacía la caché cuando se publica un mart nuevo
│   ├── scripts/gestionar_usuarios.py           # CLI de administración de usuarios
│   ├── templates/login.html
│   ├── assets/                                 # Estilos, logos, favicon
│   ├── docker/{Dockerfile,docker-compose.yml}
│   ├── requirements.txt
│   └── .env.example
├── docker/{Dockerfile,docker-compose.yml}      # Contenedores de Airflow
├── tests/                                      # Pruebas unitarias (pytest) e integración
├── requirements.txt                            # Dependencias de scripts/ fuera de Docker
└── requirements-dev.txt                        # pytest
```

> Los binarios del shapefile de CONALI (~223 MB) nunca van a Git: se transfieren por `scp` a la VM. El comando y el
> esquema de atributos están en [`mart/data/shapefiles/parroquial/README.md`](mart/data/shapefiles/parroquial/README.md).

## 5. Pipeline de datos

### 5.1 Detección automática — `sietel_detector_cambios`

Corre todos los días a las **06:00**, fuera del horario laboral.

```
detectar_cambios_sietel >> hay_cambios (short-circuit) >> disparar_carga
```

1. Calcula en SQL Server una **huella por `(anio, periodoNumero)`**:
   - `VALineasDedicadas`: número de filas, suma de `numeroUsuarios` y `CHECKSUM_AGG` de las columnas que entran al
     agregado.
   - `VAFormularioLineasDedicadas`: lo mismo, más la fecha de carga o modificación más reciente.
2. La compara con `staging.huella_fuente`, que guarda la huella de lo último cargado y certificado.
3. Si algún mes es nuevo, cambió o desapareció del origen, dispara la carga **solo de esos meses**. Si solo cambiaron
   formularios, dispara la carga sin meses de hechos (recarga los formularios y reconstruye el mart).

La huella no certifica contenido, solo responde "¿cambió algo?". La certificación real la hace la validación cruzada
de cada carga. Sin el índice de producción (ver [14.3](#143-índice-de-sql-server)), calcular la huella tarda unos
**8 minutos**.

### 5.2 Capa 1 — `sietel_usuarios_cuentas_pipeline`

```
tomar_huella_fuente >> aplicar_esquema >> cargar_dimensiones >> cargar_nodos_isp >> cargar_formularios_lineas
    >> cargar_hechos_de_anio.expand(lote)          # lotes de obtener_periodos_a_cargar
    >> validar_carga >> guardar_huella_fuente >> disparar_mart_pipeline
```

| Tarea                        | Qué hace                                                                                                                                                                                                                        |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `tomar_huella_fuente`        | Toma la huella de SIETEL **antes** de cargar. Si el origen cambia durante la carga, la huella guardada queda vieja y el detector lo vuelve a ver                                                                                |
| `aplicar_esquema`            | Aplica `sql/01_ddl_postgres.sql`. Las tablas son idempotentes; las vistas de `analitico` se recrean (ver [16.4](#164-el-dashboard-muestra-no-existe-la-relación-martvw_))                                                         |
| `cargar_dimensiones`         | SCD Tipo 2 de `dim_isp` y `dim_permiso_va_agregado`                                                                                                                                                                             |
| `cargar_nodos_isp`           | SCD Tipo 2 de `dim_nodo_isp`. `dbo.NodoISP_Auxiliar` se excluye: está congelada desde 2014 y no tiene PEVA propios                                                                                                              |
| `cargar_formularios_lineas`  | Snapshot completo de `VAFormularioLineasDedicadas`, única fuente de las declaraciones "sin servicio"                                                                                                                             |
| `obtener_periodos_a_cargar`  | Decide qué cargar, en este orden: `conf["periodos"]` (meses puntuales), `conf["anios"]` (años completos) o la Variable `sietel_anios_a_cargar`                                                                                    |
| `cargar_hechos_de_anio`      | Una tarea por año con sus meses. Por mes: extrae agregado, hace upsert con hash MD5 y borra las combinaciones que el origen ya no reporta. Los cambios quedan auditados en `staging.historial_correcciones`                       |
| `validar_carga`              | Certifica los mismos meses cargados contra SQL Server (ver [14.1](#141-certificación-de-la-carga)). Regla `none_failed`: corre aunque no haya meses de hechos, pero no si una carga falló                                          |
| `guardar_huella_fuente`      | Registra la huella de los meses cargados y de los formularios. Solo corre si la validación pasó                                                                                                                                 |
| `disparar_mart_pipeline`     | Dispara las capas 2 y 3. Solo si todo lo anterior terminó bien: nada sin certificar llega al dashboard                                                                                                                          |

El DAG tiene `max_active_runs=1`: un segundo disparo queda en cola en vez de correr en paralelo.

### 5.3 Capas 2 y 3 — `sietel_mart_pipeline`

```
aplicar_ddl_calidad >> detectar_conflictos_peva >> construir_capa2 >> limpiar_coordenadas_nodo_isp
    >> cargar_parroquias >> detectar_discrepancias_geografia_nodo >> aplicar_capa3
```

| Tarea                                   | Qué hace                                                                                                                                                                                  |
|-----------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `aplicar_ddl_calidad`                   | Aplica `sql/04_ddl_calidad.sql` (idempotente)                                                                                                                                              |
| `detectar_conflictos_peva`              | Clasifica RUC con varios PEVA en `calidad.conflictos_ruc_peva`: **A** duplicado por codificación heredada (resolución automática), **B** secuencia del mismo titular (manual solo si coexisten en el tiempo), **C** nombres distintos bajo el mismo RUC (siempre manual). Las columnas de revisión humana nunca se sobrescriben |
| `construir_capa2`                       | Reconstruye `capa2.lineas_dedicadas_consolidado` solo con lo reportado, excluyendo los PEVA del grupo A. Cambio atómico `_next` → actual → `_prev`                                        |
| `limpiar_coordenadas_nodo_isp`          | Geografía de nodos, parte A (ver [sección 7](#7-geografía-de-nodos-isp))                                                                                                                   |
| `cargar_parroquias`                     | Carga el shapefile de CONALI solo si la tabla está vacía                                                                                                                                   |
| `detectar_discrepancias_geografia_nodo` | Geografía de nodos, parte B                                                                                                                                                                |
| `aplicar_capa3`                         | Aplica `sql/02_ddl_mart.sql` completo como `mart_user`                                                                                                                                     |

`sql/02_ddl_mart.sql` corre en **una sola transacción**: `DROP SCHEMA mart CASCADE` y recreación completa, invariantes
bloqueantes (sección 17.0) y re-otorgamiento de permisos. Si una invariante falla, todo se revierte y el dashboard sigue
sirviendo el mart anterior. Al final escribe `mart.control_version`, que el dashboard usa para vaciar su caché.

### 5.4 SIGER_V3 — `siger_pipeline`

Réplica certificada de **SIGER_V3**, el sistema de ARCOTEL con el **estado jurídico de los títulos habilitantes** de
todos los prestadores y la **facturación por uso del espectro** (sin radiodifusión ni TV). Sobre la copia se construyen
las vistas SAI a nivel de RUC y un cruce con los prestadores de OBTEL como hallazgos de calidad revisables. El análisis
exploratorio de estos datos es un trabajo posterior: aquí solo se replica fielmente y se certifica.

```
aplicar_esquema_siger >> [cargar_servicios, cargar_concesionarios, cargar_titulos]
    >> cargar_facturacion >> hubo_recargas >> validar_siger >> construir_cruce_obtel
```

DAG **independiente** de los de SIETEL: otro servidor, otras credenciales y otra cadencia. Un fallo de SIGER no bloquea
SIETEL, y este DAG no dispara ni modifica los de SIETEL. Corre todos los días a las **02:00** (`max_active_runs=1`,
sin backfill), de modo que termina antes del detector de SIETEL (06:00) y no compiten por el PostgreSQL analítico. El
`conf` `permitir_caida` solo se pasa al dispararlo a mano desde la UI.

#### Detección de cambios

Cada tabla se recarga **solo si cambió en SIGER** (`siger/huella_siger.py`, mismo criterio que el detector de SIETEL).
Antes de extraer, se calcula en SQL Server una huella barata: `COUNT_BIG(*)` + `CHECKSUM_AGG(BINARY_CHECKSUM(...))` de
las columnas replicadas. Si coincide con la del último snapshot confirmado (`siger.huella_fuente`), la tabla no se toca
y `staging.control_cargas` registra `SIN_CAMBIOS`.

- Se recarga si: cambió el conteo o el checksum, cambió la lista de columnas, no hay huella guardada, el destino no
  tiene las filas que dice la huella o (solo facturación) se recargaron los títulos, porque `tipo_enlace` depende de ellos.
- La huella se guarda en la **misma transacción** del snapshot y se toma antes de extraer. Si la carga se revierte, o
  si SIGER cambia mientras se extrae, la próxima corrida vuelve a recargar.
- `validar_siger` corre solo si algo se recargó (`hubo_recargas`) y solo sobre esas tablas. Si una tabla no certifica,
  se borra su huella para forzar su recarga. El cruce con OBTEL corre siempre, porque OBTEL cambia aunque SIGER no.
- **Los domingos** (`DIA_RECARGA_COMPLETA`) se recargan y certifican las 4 tablas igual. Eso cubre lo que la huella no
  ve: cambios que se compensan en `CHECKSUM_AGG` y columnas `text`/`ntext`, que `BINARY_CHECKSUM` ignora.
- Para recargar todo a mano (por ejemplo, tras cambiar `siger/reglas.py`): *Trigger DAG w/ config*
  `{"forzar_recarga": true}`, o borrar la fila de la tabla en `siger.huella_fuente`.

#### Fuente

SQL Server 2012 SP2 (11.0.5058), `192.168.129.40`, base `SIGER_V3`, esquema `dbo`. Conexión con la misma lógica de
`scripts/config.py` (driver ODBC 18 y opciones TLS de SIETEL), parametrizada con las variables `SIGER_SQLSERVER_*`.
El handshake TLS con este servidor funciona sin ajustes en el contenedor (verificado el 05-oct-2026).

#### Permisos por columna

El usuario de lectura tiene permisos **por columna**: una sola columna denegada hace fallar toda la consulta (error
230). Por eso el código **nunca usa `SELECT *`** y replica solo las columnas que SQL Server deja consultar de verdad,
comprobadas con un `SELECT TOP 0` columna por columna (`siger/probar_conexion.py`, 05-oct-2026):

| Objeto                          | Se replican                                                                                           | Bloqueadas (no se traen)                                                                                                                                                                  |
|---------------------------------|-------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `dbo.TITULO_HABILITANTE`        | `THSECUENCIAL`, `IDSTH`, `THTOMO`, `THFOJA`, `UCP_CONCNUM`, `THFECHASUS`, `THFECHAVIG`, `THESTADO`    | `THPAGINA`, `THACTA`, `THUSUARIO`, `TTHSECUENCIAL`, `STHSECUENCIAL`, `THRESOLUCION`, `THFECHARES`, `THTITULO`, `THCUERPO`, `THCOBERTURA`, `THUSUARIOREG`, `THFECHAREG`, `THNUMERO_TRAMITE`, `THCONTRATO_RENOVADO` |
| `dbo.SERVICIO_TH`               | `IDSTH`, `ABREVIATURA`, `DESCRIPCION`                                                                 | `IDTSV`, `ELIMINACION`                                                                                                                                                                    |
| `dbo.VISTA_CONCESIONARIOS`      | `ucp_concnum`, `nombres`, `ci_ruc`, `ruc`                                                             | Las otras 18: ubicación (`prvnnombre`, `cantnombre`, `parrnombre`…), contacto (teléfonos, correo, dirección) y tipo (`ucp_tipoconc`, `ucpj_tipo`)                                          |
| `dbo.NR_PARAMETROS_FACTURACION` | Las 99 columnas                                                                                       | —                                                                                                                                                                                         |

Los permisos cambian con el tiempo (`THUSUARIO` estaba permitida y ya no; `THFECHASUS` figuraba denegada y hoy no lo
está). Cada carga los vuelve a verificar y **falla nombrando la columna** que se haya perdido, y avisa en el log si SIGER
empieza a exponer una columna accesible que todavía no se replica. Las listas viven en `siger/config_siger.py`
(`COLUMNAS_PERMITIDAS`) y en `sql/12_ddl_siger.sql`.

#### Reglas de datos

| Regla                    | Detalle                                                                                                                                                                                                                         |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Texto                    | `LTRIM(RTRIM(...))` (solo espacios) antes de comparar o construir llaves. En las tablas crudas el texto se guarda **sin recortar** (`ruc` es `char(13)` y conserva su relleno)                                                      |
| Tomo y foja              | Siempre texto: hay ceros a la izquierda (`010`) y sufijos (`13708A`, `08f02v`). Nunca se convierten a número                                                                                                                      |
| `contrato_key` (título)  | `tomo + '-' + foja`, recortados. Sin tomo ni foja → `'-'` (unos 7.100 títulos que no se enlazan con facturación)                                                                                                                  |
| Contrato ≠ título        | Un tomo-foja puede agrupar títulos de varios servicios (ej. `95-9579`: telefonía fija, portador y valor agregado de internet). La facturación se enlaza por **contrato**; el análisis SAI se hace por **título** filtrado por IDSTH. Nunca se mezclan en una misma tabla |
| `THSECUENCIAL`           | Es `float` en SIGER: se convierte a `bigint` y la carga falla si algún valor no es entero                                                                                                                                         |
| Universo SAI             | `IDSTH IN (9, 33, 31)`, **solo en vistas**. Se excluye el 8 (VALOR AGREGADO: SMS, contenido móvil, rastreo vehicular). Constante `IDSTH_UNIVERSO_SAI` en `siger/config_siger.py`, sincronizada a `siger.parametro_universo_sai` |
| RUC resuelto             | `ruc` de 13 dígitos → `ruc`; si no, `ci_ruc` de 13 → `ci_ruc_13`; si no, `ci_ruc` de 10 + `'001'` → `cedula_001` (97,4 % de coincidencia donde hay ambos datos); si no → `sin_ruc`. Se guarda el valor y su origen    |
| Unidad de análisis       | Concesionario/RUC. "SAI vigente" = al menos un título SAI con `THESTADO = 'VIGENTE'`. Vigencia = `MAX(THFECHAVIG)`; título de referencia = el vigente con tomo-foja                                                                 |
| Anomalías                | Se **marcan**, no se corrigen: vigencias distintas entre títulos vigentes, solo títulos sin tomo-foja, más de un título con tomo-foja                                                                                              |
| Facturación activa       | `ELIMINADO` es `bit` con NULL/0/1: activo = `COALESCE(eliminado, false) = false`, **nunca** `eliminado = false`. Las filas eliminadas se replican; el filtro va en las vistas                                                        |
| `COD_SERVICIO`           | No es único por `NOM_SERVICIO` (variantes "(r)" = uso reservado, una sin tilde). Se conservan tal cual, sin fusionar                                                                                                              |
| `tipo_enlace`            | `SIN_CONTRATO` (NULL o vacío, ej. TCS) → `TOMO_FOJA` (coincide con un `contrato_key`, sin distinguir mayúsculas, como SIGER) → `TRAMITE` (`ARCOTEL-...`; requeriría `THNUMERO_TRAMITE`, denegada) → `SIN_MATCH`                    |
| `cliente_coincide`       | Solo para `TOMO_FOJA`: `CLIENT_CODE` = `UCP_CONCNUM` de algún título del contrato. `false` puede ser una cesión o un error; no se filtra                                                                                           |

#### Patrón de carga

Lección del incidente del 25-sep-2026: el UPSERT sin borrado dejó en `staging` filas huérfanas del backup de SIETEL, y
`validar_carga.py` no las vio porque solo buscaba faltantes. En SIGER cada tabla se carga como **snapshot completo por
reemplazo en una sola transacción** (`siger/cargar_siger.py`):

1. **Origen**: verificación de permisos de las columnas exactas y conteo.
2. **Protecciones antes de tocar el destino**: 0 filas en origen → aborta; caída de más del **20 %** frente al
   snapshot anterior → aborta y pide revisión (`UMBRAL_CAIDA_MAXIMA`, configurable). Tras revisar una caída real, relanzar
   con *Trigger DAG w/ config* `{"permitir_caida": ["siger_facturacion"]}` (o `true` para todas).
3. **Transacción**: `TRUNCATE` + `INSERT` por lotes (`fetchmany`, nunca `fetchall`) y, **antes del `COMMIT`**,
   certificación de lo insertado: conteo, multiconjunto de hashes MD5 en **ambas direcciones** (faltantes y sobrantes)
   recalculado desde lo que quedó en PostgreSQL, y `hash_contenido` coherente con cada fila. Cualquier discrepancia →
   `ROLLBACK` y el snapshot anterior queda intacto.
4. **`validar_siger`**, después de las cargas: vuelve a leer SIGER completo y repite la certificación contra lo ya
   confirmado. Detecta cambios en SIGER durante la carga y cualquier edición posterior del destino. Si SIGER cambió en
   ese lapso (es una base viva), puede quedar en rojo sin que la carga esté mal: relanzar el DAG.
5. Todo queda en `staging.control_cargas` con `tipo_carga` = `siger_servicios`, `siger_concesionarios`,
   `siger_titulos`, `siger_facturacion` y `siger_validacion`.

Las consultas a SQL Server tienen tiempo límite propio (`conn.timeout` de pyodbc, `TIMEOUT_CONSULTA_S`), y cada tarea
del DAG tiene `execution_timeout` explícito (`AIRFLOW__CORE__TASK_TIMEOUT` no es una opción válida de Airflow).

#### Datos personales (LOPDP)

`VISTA_CONCESIONARIOS` incluye personas naturales identificadas solo por cédula (unas 10.700). La tabla cruda
`siger.concesionario` es la copia fiel, pero con **acceso restringido**, según la Ley Orgánica de Protección de Datos
Personales:

- `mart_user` recibe `SELECT` automático sobre toda tabla nueva de `siger` (`ALTER DEFAULT PRIVILEGES`), pero sobre
  `siger.concesionario` se **revoca** en cada aplicación del DDL. `mart_user` solo ve `siger.v_concesionario_basico`:
  código, nombre, RUC resuelto y su origen, sin cédula ni RUC crudos. La ubicación y el tipo de concesionario no se
  pueden incluir porque SIGER los deniega.
- **Ningún rol del dashboard** (`dashboard_lector`, `dashboard_auth`, `calidad_lector`, `calidad_revisor`,
  `eda_lector`) tiene acceso a `siger`. `validar_siger` lo comprueba en cada corrida y falla si no se cumple.
- `NR_PARAMETROS_FACTURACION` no tiene datos personales (solo `CLIENT_CODE` y datos técnicos de estaciones).
- `calidad.hallazgos_siger_obtel` guarda solo RUC, nombre y códigos (lo ven `calidad_lector` y `eda_lector`).

#### Cruce con OBTEL

`construir_cruce_obtel` (como `mart_user`) recalcula `calidad.hallazgos_siger_obtel` comparando por `ruc_limpio`, la
**misma** normalización de `mart/detectar_conflictos_peva.py` (`SQL_RUC_LIMPIO`, importada, no copiada). El lado OBTEL
sale de `analitico.v_ultimo_periodo_reportado_detalle.isp_ruc`, con el mismo filtro de "prueba" que el detector.

| `tipo_hallazgo`         | `detalle`                                                       | Significado                                                                 |
|-------------------------|-----------------------------------------------------------------|-----------------------------------------------------------------------------|
| `SIGER_SAI_SIN_OBTEL`   | `SIN_PEVA_EN_OBTEL`                                             | Titular SAI vigente en SIGER sin ningún PEVA vigente en OBTEL               |
| `OBTEL_SIN_SAI_VIGENTE` | `RUC_NO_EXISTE_EN_SIGER`, `SIN_TITULO_SAI`, `SAI_NO_VIGENTE`    | Prestador que reporta en OBTEL sin título SAI vigente en SIGER              |

`ruc_por_cedula_001` marca los RUC deducidos de la cédula. Es una tabla con **flujo de revisión** como
`calidad.conflictos_ruc_peva`: las columnas de revisión nunca se sobrescriben, nada se corrige automáticamente, y lo que
deja de detectarse se conserva con `sigue_detectado = false`. Si alguno de los dos lados está vacío, la tarea aborta en
vez de marcar todo como hallazgo.

#### Puesta en marcha

1. **Rol y esquema en VM1** (ya ejecutados el 05-oct-2026; referencia en `sql/11_roles_siger.sql`, que **no** se
   vuelve a ejecutar), como `postgres`:
   ```sql
   CREATE ROLE siger_user LOGIN PASSWORD '<contraseña>';
   GRANT CONNECT ON DATABASE sietel_analitico TO siger_user;
   CREATE SCHEMA siger AUTHORIZATION siger_user;
   GRANT USAGE ON SCHEMA staging TO siger_user;
   GRANT SELECT, INSERT ON staging.control_cargas TO siger_user;
   GRANT USAGE ON SEQUENCE staging.control_cargas_id_seq TO siger_user;
   GRANT USAGE ON SCHEMA siger TO mart_user;
   ALTER DEFAULT PRIVILEGES FOR ROLE siger_user IN SCHEMA siger GRANT SELECT ON TABLES TO mart_user;
   ```
   En `pg_hba.conf`, `siger_user` desde `192.168.129.51` (VM2) y `192.168.137.50`. `siger_user` **no** tiene `CREATE`
   sobre la base: `sql/12_ddl_siger.sql` no crea el esquema y falla con un mensaje claro si falta.
2. **Variables** `SIGER_*` en el `.env` de la raíz **y** en el bloque `environment` de `docker/docker-compose.yml`, que
   ya las incluye: el compose las pasa una por una y sin ellas no llegan al contenedor (ver [12.1](#121-airflow-y-capa-1-env-en-la-raíz)).
3. **Prueba de conectividad** (solo lectura), desde `docker/`:
   ```bash
   docker compose --env-file ../.env exec airflow-scheduler python /opt/airflow/siger/probar_conexion.py --pg
   ```
4. **Despausar y disparar** `siger_pipeline` en la interfaz de Airflow.

#### Supuestos no verificables en el código

- Un `THTOMO`/`THFOJA` NULL (no vacío) se trata como cadena vacía al construir `contrato_key`.
- `CLIENT_CODE` y `UCP_CONCNUM` se comparan como texto recortado; los contratos, sin distinguir mayúsculas (como la
  intercalación de SIGER, con la que se midieron los 2.729 contratos enlazados).
- OBTEL no aplica la regla `cedula_001`: un `isp_ruc` de 10 dígitos en SIETEL aparece como hallazgo en ambos sentidos.
  `longitud_ruc_obtel` y `ruc_por_cedula_001` permiten identificarlos.
- Las anomalías se cuentan por RUC: un RUC con varios concesionarios suma los títulos de todos.
- `PostgreSQL` no admite el carácter NUL en texto. Si SIGER llegara a tenerlo, la carga falla con un mensaje explícito
  en vez de limpiarlo en silencio.
- La certificación de facturación mantiene en memoria un digest por fila (unos 2,5 M, del orden de 300 MB en el worker).

## 6. Principio metodológico: nunca imputar

Es el criterio de diseño más importante del sistema. **Ninguna cifra es imputada.** Hasta septiembre de 2026, `capa2`
rellenaba los huecos de cada serie con el último valor conocido (LOCF); se eliminó por completo el 29-sep-2026 porque:

- **La falta de reporte no es aleatoria.** Un prestador que deja de reportar tiene una probabilidad
  desproporcionada de estar en crisis, saliendo del mercado o en incumplimiento. Heredar su último valor supone "sin
  cambios" cuando lo más probable es lo contrario.
- **Una combinación omitida suele ser un cero.** Si el prestador entregó su reporte pero omitió una parroquia o un tipo
  de enlace, lo más probable es que no tenga líneas ahí; el LOCF las inventaba.
- **Los totales mixtos contaminaban otros cálculos.** Se usaban donde debía ir solo lo reportado, y los totales
  históricos cambiaban retroactivamente cada vez que un prestador volvía a reportar.

Es la práctica recomendada en la literatura de datos faltantes (Rubin; Little y Rubin; NRC 2010; ICH E9(R1)
desaconsejan LOCF) y en estadística oficial: publicar lo observado junto con su cobertura.

**Cómo se resuelve lo que antes dependía del relleno:**

- **`mart.panel_reporte_prestador_mes`**: una fila por período, territorio y prestador, desde su primer hasta su último
  reporte en ese territorio, con `reporto` (sí/no) y **sin ningún valor de líneas**. Es el denominador de la
  cobertura (`numero_prestadores_esperados`, `porcentaje_cobertura_prestadores`) en los hechos de mercado, IHH y
  participación.
- **Participación e IHH** se calculan solo con quienes reportaron ese mes. Los esperados que no reportaron aparecen
  como `SIN_REPORTE_ESTE_MES`, nunca con 0 % ni con su último valor.
- **Alerta de prestador dominante ausente**: un prestador que alguna vez alcanzó ≥30 % de participación nacional y no
  reportó ese mes. Acotada a nivel **nacional**: en provincias con pocos competidores, prestadores pequeños superan el
  30 % y quedarían marcados como ausentes para siempre.
- **Series de totales**: cada punto viaja con su cobertura, porque una caída del total puede ser falta de reporte y no
  del mercado.
- **"Dejaron de reportar"** tiene una sola definición en Evolución y Control: activos el mes anterior que no lo están
  este mes, comparando meses calendario.
- **Obligación de reportar**: empieza un año calendario después de la fecha del título habilitante.
- **Guardas contra la reintroducción**: la invariante 17.9 de `sql/02_ddl_mart.sql` aborta el refresco si aparece una
  columna de imputación, y `tests/test_sin_imputacion.py` falla si el código vuelve a rellenar huecos.

**Límites reconocidos:**

- Tras el último reporte de un prestador, el panel no distingue "salió del mercado" de "dejó de reportar". Lo cubren
  `mart.vw_prestadores_reporte_detenido` (con 3 meses de margen) y la alerta de dominante ausente.
- Quien **nunca** reportó no aparece en `capa2` ni en el panel; se ve en `mart.vw_prestadores_sin_reportar`, solo a
  nivel nacional, porque SIETEL no tiene su geografía.
- Los totales de meses con baja cobertura son menores que los de la versión con LOCF (en diciembre de 2013, cerca de
  dos tercios del total anterior era imputado). No es una caída del mercado: es lo reportado. Una serie continua, si se
  necesitara, debe ser una estimación rotulada y separada del mart.

## 7. Geografía de nodos ISP

`dbo.NodoISP` registra la ubicación física de la infraestructura de acceso. No tiene relación 1:1 con la geografía de
las líneas (un nodo puede servir varias parroquias), por eso vive en tablas, vistas y filtros separados.

**Parte A — Limpieza de coordenadas** (`mart/limpiar_coordenadas_nodo_isp.py` → `capa2.nodo_isp_geocodificado`).
Latitud y longitud son texto libre en formato DMS inconsistente. El parser nunca adivina: si no puede convertir con
certeza, marca `es_coordenada_valida = false` con el motivo. La única inferencia deliberada es el signo de la
**longitud** sin hemisferio, porque Ecuador está 100 % al oeste de Greenwich; nunca se aplica a la latitud, ya que
Ecuador cruza la línea ecuatorial.

**Parte B — Cruce espacial** (`mart/cargar_parroquias.py` y `mart/detectar_discrepancias_geografia_nodo.py`). La
fuente cartográfica es el shapefile parroquial de **CONALI**, tratado como autoritativo por tener una codificación INEC
más reciente que `dbo.Parroquia`.

- `capa2.parroquias_geometria`: geometría íntegra por parroquia (1.052), usada en el cruce real.
- `capa2.territorio_geometria_nodo`: cantón y provincia disueltos y simplificados, solo para dibujar el mapa. El
  shapefile tenía 21,8 millones de vértices y colgaba el navegador; tras simplificar quedan 313 mil (−98,6 %).
- El cruce usa `shapely.STRtree` con `covers()` (incluye la frontera) y produce
  `capa2.nodo_isp_geografia_resuelta` (todos los nodos con match) y `calidad.discrepancias_geografia_nodo` (solo los
  que discrepan, con flujo de revisión humana).

**La comparación es por cantón, no por parroquia.** Por parroquia salían 3.976 "discrepancias" sobre 7.021 nodos
válidos (56,6 %); el 91 % eran el mismo lugar con dos convenciones de código (cabecera cantonal `XX01` en SIETEL frente
a `XX50` en CONALI). Por cantón quedan 360 discrepancias reales (5,1 %). Límite aceptado: puede escaparse una
discrepancia dentro del mismo cantón (caso Sígsig, Azuay).

## 8. Dashboard

Aplicación Dash multipágina servida con gunicorn (4 workers `gthread` × 4 hilos) y autenticada con Flask-Login.
Tras el login, `/` muestra el panel de selección de módulos.

### 8.1 Módulo SAI (`sietel_analitico`, esquema `mart`)

| Página                        | Ruta                            | Contenido                                                                                                                                                                                                                                             |
|-------------------------------|---------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Evolución                     | `/sai/evolucion`                | Cuentas y prestadores por mes con cobertura, tasa de entrega de reportes, prestadores que nunca reportaron, composición y diferencia mensual por rango de velocidad, y **Cuentas por territorio** (desglose un nivel más abajo, con clic para bajar) |
| IHH y participación           | `/sai/concentracion`            | IHH histórico con alerta de dominante ausente (una serie por prestador), cobertura, líder, CR2/CR4, participación individual y aporte al IHH                                                                                                          |
| Mapa de nodos                 | `/sai/mapa-nodos`               | Nodos sin discrepancia, coloreados por tipo, con auto-zoom al territorio y nodos por provincia                                                                                                                                                        |
| Discrepancias de geografía    | `/sai/discrepancias-geografia`  | Nodos cuyo cantón reportado no coincide con el de su coordenada. Solo lectura                                                                                                                                                                          |
| Control                       | `/sai/control`                  | Nunca han reportado, reporte detenido y variación mensual anómala de cuentas                                                                                                                                                                          |
| Conflictos RUC/PEVA           | `/sai/conflictos-ruc-peva`      | Cola de conflictos de identidad (categorías A/B/C) para priorizar la revisión. Por defecto muestra solo los pendientes que siguen detectados. Solo lectura                                                                                            |
| Prioridad de carga            | `/sai/prioridad-carga`          | A quién exigir la carga según su impacto: reporte detenido ordenado por peso histórico (con heatmap de meses reportados) y nunca reportaron ordenados por antigüedad del permiso. Los dominantes (≥30 %) van primero                                  |

Las revisiones de conflictos y discrepancias se registran fuera de OBTEL con el rol `calidad_revisor`; el dashboard
solo las muestra.

### 8.2 Módulo SMA (`samm_db`)

| Página                     | Ruta         | Estado                                                                                                                                                                                  |
|----------------------------|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Calidad de Datos móviles   | `/sma/datos` | Réplica del reporte de Power BI sobre `public.grafana_mobile_geo_view`: % de cumplimiento, sesiones HTTP fallidas, throughput por operadora (`SimOperator`) y mapa muestreado          |
| Calidad de Voz             | `/sma/voz`   | **Pausada**: no se consultará la base hasta contar con las medidas DAX reales de voz, para no publicar cifras basadas en supuestos                                                        |

`PhoneNumber`, `IMEI` e `IMSI` nunca se exponen en agregados ni en listados.

### 8.3 Filtros

Hay tres universos geográficos que nunca se mezclan:

| Componente                    | Páginas                      | Universo                                        | Selección                                              |
|-------------------------------|------------------------------|-------------------------------------------------|--------------------------------------------------------|
| `territory_filters.py`        | Evolución, Concentración     | Geografía de **líneas** (`mart.dim_territorio`) | Única, en cascada Provincia → Cantón → Parroquia; vacío = Nacional |
| `node_territory_filters.py`   | Mapa de nodos, Discrepancias | Geografía de **nodos** (CONALI)                 | Múltiple e independiente por nivel                     |
| `lines_territory_filters.py`  | Control                      | Geografía de **líneas**                         | Múltiple e independiente por nivel                     |

- **Sin "Nivel geográfico"** (desde el 29-sep-2026): el nivel es el más profundo elegido. La selección única en
  Evolución y Concentración es deliberada: el IHH se calcula sobre un mercado; para comparar territorios está
  "Cuentas por territorio".
- **Estado de operación y Prestador** se comparten entre todas las páginas SAI; **Desde/Hasta** entre Evolución,
  Concentración y Control. SMA tiene su propio filtro compartido (`sma_filters.py`).
- **Filtrado cruzado Prestador → territorio** en Control, Mapa de nodos y Discrepancias: elegir un prestador acota las
  provincias, cantones y parroquias a donde tiene presencia.
- **Los filtros de Control no aplican igual a sus tres secciones**, por la forma de cada fuente: "Nunca han reportado"
  solo admite Estado/Prestador (la vista no tiene geografía ni período); en "Reporte detenido" el territorio significa
  "reportó alguna vez ahí" y Desde/Hasta filtra por la fecha del último reporte; "Variación mensual" aplica los cinco
  filtros recalculando dentro del territorio.

Todas las tablas tienen descarga a Excel del contenido en pantalla.

### 8.4 Caché y rendimiento

- **Flask-Caching con `FileSystemCache`**, compartido por todos los workers. Las consultas se memoizan entre 5 y 60
  minutos.
- **Invalidación automática** (`services/cache_mart.py`): como máximo una vez por minuto por proceso, el dashboard lee
  `mart.control_version`; si cambió, vacía la caché. Los datos nuevos aparecen en menos de un minuto tras el refresco
  del mart, sin reiniciar el contenedor.
- **Pool de conexiones acotado** (`3+5` para `mart`, `2+2` para `auth` por proceso): la instancia de VM1 tiene
  `max_connections=100` compartidas con Airflow y `samm_pipeline`.
- **Conversiones vectorizadas** en las consultas de opciones (130 veces más rápidas que `.iterrows()` con 1.369
  prestadores) y proyección de solo las columnas usadas en el mapa de nodos.

### 8.5 Seguridad

- Contraseñas con bcrypt; cookies de sesión firmadas con `SECRET_KEY`, `HttpOnly` y `SameSite=Lax`.
- Sin autorregistro: los usuarios se gestionan solo con `dashboard/scripts/gestionar_usuarios.py`, usando credenciales
  administrativas distintas del rol de ejecución `dashboard_auth`.
- El guard de autenticación bloquea todas las rutas salvo `/login`, `/logout` y los endpoints internos de Dash.
- Mismo mensaje de error para usuario inexistente, contraseña incorrecta o usuario inactivo.
- Límite de intentos fallidos: 5 por usuario y 50 por IP, con bloqueo de 15 minutos. Los contadores viven en la
  caché, así que se reinician cuando la caché se vacía tras un refresco del mart.
- `APP_DEBUG=false` y gunicorn obligatorios en producción.
- **Pendiente**: el dashboard se sirve por HTTP en la red interna (la contraseña y la cookie viajan sin cifrar) y el
  formulario de login no tiene token CSRF. Requiere un certificado institucional y un proxy TLS; al tenerlo, activar
  `SESSION_COOKIE_SECURE=true`.

## 9. Modelo de datos

### 9.1 `staging` (Capa 1, tablas)

| Tabla                              | Contenido                                                                                                                         |
|------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `va_lineas_dedicadas_resumen`      | Hechos agregados. Llave natural: `peva_codigo, par_codigo, periodoNumero, anio, tipoEnlace, tipoCliente, nivelComparticion, portador` |
| `va_formulario_lineas_dedicadas`   | Cabecera de cada entrega del formulario, incluidas las declaraciones "sin servicio"                                               |
| `dim_isp`                          | ISP, SCD Tipo 2                                                                                                                   |
| `dim_permiso_va_agregado`          | Permisos (PEVA), SCD Tipo 2                                                                                                       |
| `dim_nodo_isp`                     | Nodos ISP, SCD Tipo 2, con códigos INEC                                                                                            |
| `historial_correcciones`           | Snapshot JSONB de cada fila cuyo contenido cambió o que el origen dejó de reportar (trigger `trg_registrar_correccion_resumen`)    |
| `control_cargas`                   | Auditoría de cada carga, validación y detección                                                                                   |
| `huella_fuente`                    | Huella de SIETEL por fuente y `(anio, periodo_numero)` de lo último cargado y certificado                                          |

### 9.2 `analitico` (Capa 1, vistas de consumo)

| Vista                                  | Uso                                                                                                                  |
|----------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `v_lineas_dedicadas_resumen`           | Serie histórica con dimensiones resueltas por vigencia temporal                                                      |
| `v_ultimo_periodo_reportado_detalle`   | Último período de cada prestador vigente, incluidos los que nunca reportaron (`tiene_reportes = false`)             |
| `v_formularios_lineas_por_peva`        | Resumen de entregas del formulario por PEVA (fuente de la clasificación "sin servicio")                              |
| `v_nodo_isp_vigente`                   | Nodos vigentes con coordenadas crudas y códigos INEC                                                                 |

### 9.3 `calidad` y `capa2` (Capa 2)

| Objeto                                   | Contenido                                                                                      |
|------------------------------------------|------------------------------------------------------------------------------------------------|
| `calidad.conflictos_ruc_peva`            | RUC con varios PEVA, clasificados A/B/C, con flujo de revisión persistente                    |
| `calidad.vw_pevas_excluidos`             | PEVA del grupo A que `construir_capa2` excluye                                                  |
| `calidad.discrepancias_geografia_nodo`   | Nodos con cantón reportado distinto al de su coordenada, con flujo de revisión                  |
| `calidad.hallazgos_siger_obtel`          | Cruce SIGER ↔ OBTEL por RUC, con flujo de revisión (ver [5.4](#54-siger_v3--siger_pipeline))    |
| `capa2.lineas_dedicadas_consolidado`     | Lo reportado por PEVA, geografía, características y mes, sin relleno                            |
| `capa2.nodo_isp_geocodificado`           | Nodos con coordenadas decimales validadas                                                       |
| `capa2.parroquias_geometria`             | Geometría íntegra por parroquia (CONALI)                                                        |
| `capa2.territorio_geometria_nodo`        | Geometría simplificada de cantón y provincia para el mapa                                       |
| `capa2.nodo_isp_geografia_resuelta`      | Todos los nodos con match espacial, geografía CONALI                                            |

### 9.4 `mart` (Capa 3)

| Tipo                    | Objetos                                                                                                                                                                                 |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Dimensiones y puentes   | `dim_periodo`, `dim_prestador`, `dim_geografia`, `dim_territorio`, `dim_territorio_nodo`, `bridge_geografia_territorio`, `bridge_prestador_peva`                                         |
| Hechos (vistas materializadas) | `fact_lineas_geografia_mes`, `fact_lineas_velocidad_mes`, `fact_resumen_mercado_mes`, `fact_velocidad_mercado_mes`, `fact_participacion_mercado`, `fact_ihh_geografico`, `panel_reporte_prestador_mes` |
| Cumplimiento            | `vw_prestadores_sin_reportar`, `vw_prestadores_reporte_detenido`                                                                                                                        |
| Calidad (puentes de solo lectura) | `vw_conflictos_ruc_peva`, `vw_nodos_isp_mapa`                                                                                                                                  |
| Geografía de nodos      | `vw_geometria_territorio_nodo`, `vw_dashboard_filtros_geograficos_nodo`                                                                                                                  |
| Consumo del dashboard   | `vw_dashboard_evolucion`, `vw_dashboard_ihh`, `vw_dashboard_participacion`, `vw_dashboard_velocidades`, `vw_dashboard_filtros_geograficos`                                               |
| Auditoría y control     | `audit_prestadores_prueba`, `audit_conflictos_peva`, `vw_auditoria_resolucion_peva`, `control_version`                                                                                   |

### 9.5 Rangos de velocidad

Las columnas `lineas_dl_*` (bajada) y `lineas_ul_*` (subida) cuentan **líneas**, no usuarios finales:

| Sufijo          | Rango (Kbps)        | Referencia         |
|-----------------|---------------------|--------------------|
| `sin_datos`     | NULL o 0            | No reportado       |
| `menos_1mbps`   | < 1.024             | Brecha digital     |
| `1_10mbps`      | 1.024 – 10.239      | Umbral mínimo UIT  |
| `10_30mbps`     | 10.240 – 30.719     | Umbral básico OCDE |
| `30_100mbps`    | 30.720 – 102.399    | Umbral UE          |
| `100mbps_1gbps` | 102.400 – 1.048.575 | Ultra banda ancha  |
| `1gbps_o_mas`   | ≥ 1.048.576         | Gigabit            |

`codigo_provincia`, `codigo_ciudad` y `codigo_parroquia` son `VARCHAR` para conservar ceros a la izquierda. No forman
parte del hash ni de las columnas versionables: son metadatos derivados de `par_codigo`.

### 9.6 `siger` (SIGER_V3, dueño `siger_user`)

| Objeto                          | Tipo   | Contenido                                                                                                                       |
|---------------------------------|--------|---------------------------------------------------------------------------------------------------------------------------------|
| `servicio_th`                   | Tabla  | Copia fiel de `dbo.SERVICIO_TH` (40 tipos de servicio, incluida radiodifusión y TV)                                               |
| `titulo_habilitante`            | Tabla  | Copia fiel de `dbo.TITULO_HABILITANTE`, todos los servicios y estados, más `contrato_key`                                         |
| `concesionario`                 | Tabla  | Copia fiel de `dbo.VISTA_CONCESIONARIOS`, más `ruc_resuelto` y `ruc_origen`. **Datos personales: sin acceso para `mart_user`**    |
| `facturacion_espectro`          | Tabla  | Copia fiel de `dbo.NR_PARAMETROS_FACTURACION` (99 columnas, incluidas las eliminadas), más `contrato_key` y `tipo_enlace`         |
| `parametro_universo_sai`        | Tabla  | IDSTH del universo SAI, sincronizado desde `siger/config_siger.py`                                                                 |
| `huella_fuente`                 | Tabla  | Huella (conteo + checksum) de cada tabla en su último snapshot; si no cambia, la tabla no se recarga                             |
| `v_titulo_sai`                  | Vista  | Títulos del universo SAI, con `es_vigente` y `con_tomo_foja`                                                                      |
| `v_prestador_sai`               | Vista  | Una fila por RUC con título SAI: vigencia, título de referencia, origen del RUC y banderas de anomalía                            |
| `v_facturacion_contrato`        | Vista  | Facturación con `activo` y `cliente_coincide`, una fila por fila de origen                                                        |
| `v_concesionario_basico`        | Vista  | Código, nombre, RUC resuelto y origen: lo único de los concesionarios que ve `mart_user`                                          |

Todas las tablas crudas llevan `hash_contenido` (MD5 de las columnas de origen) y `fecha_carga`. Ningún filtro de
servicio, estado o eliminación se aplica en las tablas: solo en las vistas.

## 10. Requisitos

**Infraestructura**

- Docker con Compose v2 en la VM de Airflow y del dashboard.
- Acceso de red a SIETEL (puerto 1433) y a PostgreSQL de VM1 (puerto 5432).
- Base `sietel_analitico` y base de metadata de Airflow ya creadas en PostgreSQL.
- Usuario de SQL Server con `SELECT` sobre `VALineasDedicadas`, `VAFormularioLineasDedicadas`, `ISP`,
  `PermisoVAgregado`, `NodoISP`, `Parroquia`, `Ciudad` y `Provincia`.
- Shapefile parroquial de CONALI (`ORGANIZACION_TERRITORIAL_PARROQUIAL.*`).

**Versiones de software**

| Componente                         | Versiones                                                                                                                                  |
|------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| Airflow (`docker/Dockerfile`)      | `apache/airflow:slim-3.3.0-python3.14`, ODBC Driver 18                                                                                     |
| Capa 1 (`requirements.txt`)        | pyodbc 5.3.0, psycopg2-binary 2.9.12, python-dotenv 1.2.2                                                                                  |
| Capas 2 y 3 (`mart/requirements.txt`) | SQLAlchemy 2.0.51, psycopg[binary] 3.3.4, python-dotenv 1.2.2, geopandas 1.1.4 (shapely llega como dependencia)                        |
| Dashboard (`dashboard/requirements.txt`) | dash 4.4.1, dash-ag-grid 35.3.0, dash-mantine-components 2.8.0, plotly 7.0.0, pandas 3.0.5, openpyxl 3.1.5, SQLAlchemy 2.0.51, psycopg[binary] 3.3.4, Flask-Caching 2.4.1, Flask-Login 0.6.3, bcrypt 5.0.0, gunicorn 26.0.0, python-dotenv 1.2.2 |
| Desarrollo (`requirements-dev.txt`) | pytest 9.1.1                                                                                                                              |

`dash-mantine-components` requiere fijar `_dash_renderer._set_react_version("18.2.0")` antes de instanciar `Dash()`
(ver `dashboard/app.py`).

## 11. Instalación y puesta en marcha

### 11.1 Archivos de entorno

| Archivo           | Lo usan                                                    | Plantilla                                   |
|-------------------|------------------------------------------------------------|---------------------------------------------|
| `.env` (raíz)     | Airflow (`docker/docker-compose.yml`) y `scripts/` locales | Ver [12.1](#121-airflow-y-capa-1-env-en-la-raíz) |
| `mart/.env`       | Ejecución local de `mart/*.py`                              | Ver [12.2](#122-capas-2-y-3-martenv)         |
| `dashboard/.env`  | Contenedor del dashboard                                    | `dashboard/.env.example`                    |

Ninguno se versiona (`.gitignore`).

### 11.2 Primera instalación

1. **Crear los roles de PostgreSQL** por línea de comandos en VM1: `mart_user`, `dashboard_lector`,
   `dashboard_auth`, `calidad_lector`, `calidad_revisor`, `eda_lector`.
2. **Aplicar los permisos base conectado como `mart_user`**, en este orden: `sql/00_roles_mart.sql` →
   `sql/03_ddl_auth.sql` → `sql/04_ddl_calidad.sql` → `sql/05_roles_eda.sql`.
3. **Dar a `mart_user` lectura sobre `analitico`** (como `sietel_user` o superusuario):
   ```sql
   GRANT USAGE ON SCHEMA analitico TO mart_user;
   GRANT SELECT ON analitico.v_ultimo_periodo_reportado_detalle TO mart_user;
   GRANT SELECT ON analitico.v_lineas_dedicadas_resumen TO mart_user;
   GRANT SELECT ON analitico.v_nodo_isp_vigente TO mart_user;
   ```
4. **Transferir el shapefile de CONALI** a `mart/data/shapefiles/parroquial/`.
5. **Levantar Airflow** desde `docker/`:
   ```bash
   docker compose --env-file ../.env up -d --build
   ```
6. **Carga histórica**: Variable `sietel_anios_a_cargar = historico` y disparar
   `sietel_usuarios_cuentas_pipeline`. Al terminar dispara `sietel_mart_pipeline` (debe estar despausado).
7. **Sembrar la huella** del detector, con PostgreSQL ya al día:
   ```bash
   docker compose --env-file ../.env exec airflow-scheduler python /opt/airflow/scripts/detectar_cambios.py --sembrar
   ```
8. **Despausar** `sietel_detector_cambios`, `sietel_usuarios_cuentas_pipeline` y `sietel_mart_pipeline`.
9. **Levantar el dashboard** desde `dashboard/docker/` (lee `dashboard/.env`):
   ```bash
   docker compose up -d --build
   ```
10. **Crear el primer usuario** (ver [13.4](#134-usuarios-del-dashboard)).

### 11.3 Roles y permisos de PostgreSQL

| Rol                | Acceso                                                                                  | Usado por                                        |
|--------------------|-----------------------------------------------------------------------------------------|--------------------------------------------------|
| `sietel_user`      | Dueño de `staging` y `analitico`                                                        | Capa 1 y metadata de Airflow                      |
| `mgonzalez`        | Lectura de `analitico`                                                                  | Power BI                                          |
| `mart_user`        | Dueño de `capa2`, `mart` y `calidad`; lectura de las vistas de `siger` (no de `siger.concesionario`) | Capas 2 y 3, cruce SIGER ↔ OBTEL |
| `siger_user`       | Dueño de `siger`; `SELECT`/`INSERT` en `staging.control_cargas`; sin `CREATE` en la base | `siger_pipeline` (ver [5.4](#54-siger_v3--siger_pipeline)) |
| `dashboard_lector` | `SELECT` sobre `mart.*`                                                                 | Dashboard (datos)                                 |
| `dashboard_auth`   | `SELECT`/`INSERT`/`UPDATE` sobre `auth.usuarios_dashboard`                               | Dashboard (login)                                 |
| `calidad_lector`   | `SELECT` sobre `calidad.*`                                                               | Consulta de calidad                               |
| `calidad_revisor`  | Lo anterior más `UPDATE` de las columnas de revisión                                    | Revisión de conflictos y discrepancias           |
| `eda_lector`       | `SELECT` sobre `mart.*` y `calidad.*`, `statement_timeout = 30min`                       | Análisis exploratorio (Jupyter)                   |
| `samm_user`        | Dueño de `samm_db`                                                                      | Módulo SMA del dashboard (riesgo aceptado: no es de solo lectura) |

- Los scripts SQL **asumen que el rol ya existe** y fallan con un error explícito si no.
- Deben ejecutarse **conectado como `mart_user`**. Aplicados como `postgres`, los objetos quedan con dueño `postgres` y
  `mart/*.py` falla al escribir (se corrige con `ALTER TABLE ... OWNER TO mart_user`).
- `sql/02_ddl_mart.sql` hace `DROP SCHEMA mart CASCADE`, que borra los `GRANT`. Por eso su sección 18 los re-otorga y
  los scripts de rol usan `ALTER DEFAULT PRIVILEGES FOR ROLE mart_user`.

## 12. Configuración

### 12.1 Airflow y Capa 1 (`.env` en la raíz)

| Variable                                                    | Requerida | Descripción                                            |
|-------------------------------------------------------------|-----------|--------------------------------------------------------|
| `SIETEL_SQLSERVER_HOST`                                     | Sí        | Servidor de SIETEL                                     |
| `SIETEL_SQLSERVER_DATABASE`                                 | Sí        | `SIETEL`                                               |
| `SIETEL_SQLSERVER_USER` / `SIETEL_SQLSERVER_PASSWORD`       | Sí        | Credenciales de SQL Server                             |
| `SIETEL_SQLSERVER_PORT`                                     | No        | Por defecto `1433`                                     |
| `SIETEL_SQLSERVER_ODBC_DRIVER`                              | No        | Por defecto `ODBC Driver 18 for SQL Server`            |
| `ANALITICO_PG_HOST` / `ANALITICO_PG_DATABASE`               | Sí        | PostgreSQL de VM1, `sietel_analitico`                  |
| `ANALITICO_PG_USER` / `ANALITICO_PG_PASSWORD`               | Sí        | `sietel_user`                                          |
| `ANALITICO_PG_PORT`                                         | No        | Por defecto `5432`                                     |
| `MART_USER_USER` / `MART_USER_PASSWORD`                     | Sí        | Credenciales de `mart_user` (tareas de capas 2 y 3)    |
| `SIGER_SQLSERVER_HOST` / `SIGER_SQLSERVER_DATABASE`         | Sí        | SIGER_V3: `192.168.129.40`, `SIGER_V3`                 |
| `SIGER_SQLSERVER_USER` / `SIGER_SQLSERVER_PASSWORD`         | Sí        | Usuario de lectura de SIGER (permisos por columna)     |
| `SIGER_SQLSERVER_PORT`                                      | No        | Por defecto `1433`                                     |
| `SIGER_PG_USER` / `SIGER_PG_PASSWORD`                       | Sí        | `siger_user`; host, puerto y base son los de `ANALITICO_PG_*` |
| `AIRFLOW_METADATA_PG_HOST` / `_PORT` / `_DATABASE` / `_USER` / `_PASSWORD` | Sí | Base de metadata de Airflow                  |
| `AIRFLOW__CORE__FERNET_KEY` / `AIRFLOW__API_AUTH__JWT_SECRET` | Sí      | Secretos de Airflow                                    |
| `_AIRFLOW_WWW_USER_USERNAME`                                | Sí        | Usuario administrador de la interfaz                   |
| `AIRFLOW_WEBSERVER_PORT`                                    | No        | Por defecto `8081`                                     |
| `LOG_LEVEL`                                                 | No        | Por defecto `INFO`                                     |

Las variables `SIGER_*` deben estar **en el `.env` y en el bloque `environment` del compose** (ya incluidas): el compose
pasa las variables una por una, y una que no figure ahí no llega al contenedor.

`AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG=1` (fijo en el compose) limita la concurrencia para no saturar SIETEL.
`ANIO_INICIO_HISTORICO` (2011) y `ANIO_FIN_HISTORICO` (2025) se definen solo en `scripts/config.py`.

### 12.2 Capas 2 y 3 (`mart/.env`)

Solo para ejecutar `mart/*.py` fuera de Airflow: `MART_USER_USER`, `MART_USER_PASSWORD`, `ANALITICO_PG_HOST`,
`ANALITICO_PG_PORT`, `ANALITICO_PG_DATABASE` y `LOG_LEVEL`.

### 12.3 Dashboard (`dashboard/.env`)

| Variable                                                        | Descripción                                                                           |
|-----------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `MART_PG_HOST` / `_PORT` / `_DATABASE` / `_USER` / `_PASSWORD`  | Conexión de datos, rol `dashboard_lector`                                             |
| `AUTH_PG_HOST` / `_PORT` / `_DATABASE` / `_USER` / `_PASSWORD`  | Conexión de login, rol `dashboard_auth`                                               |
| `SMA_PG_HOST` / `_PORT` / `_DATABASE` / `_USER` / `_PASSWORD`   | Módulo SMA, base `samm_db`                                                            |
| `SECRET_KEY`                                                    | Firma de cookies. Generar con `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_COOKIE_SECURE`                                         | `true` solo si se sirve por HTTPS; con HTTP debe ser `false` o nadie podrá iniciar sesión |
| `APP_HOST` / `APP_PORT` / `APP_DEBUG`                           | Por defecto `0.0.0.0` / `8050` / `false`                                              |
| `CACHE_TIMEOUT`                                                 | Segundos por defecto de la caché, `300`                                               |
| `CACHE_TYPE` / `CACHE_DIR`                                      | Por defecto `FileSystemCache` / `/tmp/obtel-dashboard-cache`                          |

## 13. Operación

### 13.1 Actualización automática

No requiere intervención: el detector revisa SIETEL a diario y, si hay cambios, encadena la carga y el mart. Conviene
revisar Airflow al inicio de la jornada; si un DAG quedó en rojo, ver [sección 16](#16-solución-de-problemas).

### 13.2 Cargas manuales en Airflow

| Qué se necesita                     | Cómo                                                                                          |
|-------------------------------------|-----------------------------------------------------------------------------------------------|
| Meses puntuales                     | *Trigger DAG w/ config* en `sietel_usuarios_cuentas_pipeline` con `{"periodos": [[2025, 12]]}` |
| Años completos                      | *Trigger DAG w/ config* con `{"anios": [2024, 2025]}`                                          |
| Según la Variable                   | Disparo sin config; usa `sietel_anios_a_cargar` (tabla abajo)                                  |
| Solo refrescar el dashboard         | Disparar `sietel_mart_pipeline`                                                                |

| `sietel_anios_a_cargar` | Comportamiento                                              |
|-------------------------|-------------------------------------------------------------|
| `historico`             | `ANIO_INICIO_HISTORICO`..`ANIO_FIN_HISTORICO`               |
| `2025`                  | Ese año                                                     |
| `2023,2024,2025`        | Esa lista                                                   |
| Ausente u otro valor    | El año en curso                                             |

Toda carga actualiza la huella de los meses que certifica. **Hasta que termine `sietel_mart_pipeline`, las páginas que
dependen de `vw_prestadores_sin_reportar` y `vw_nodos_isp_mapa` fallan** (ver [16.4](#164-el-dashboard-muestra-no-existe-la-relación-martvw_)):
evitar cargas manuales en horario laboral.

### 13.3 Línea de comandos

Dentro del contenedor de Airflow, desde `docker/`, anteponer
`docker compose --env-file ../.env exec airflow-scheduler python /opt/airflow/...`. Localmente, con el `.env`
correspondiente:

```bash
# Capa 1
python scripts/aplicar_esquema.py
python scripts/cargar_dimensiones.py
python scripts/cargar_nodo_isp.py
python scripts/cargar_formularios_lineas.py
python scripts/cargar_hechos_anio.py --anio 2025            # año completo
python scripts/cargar_hechos_anio.py --anio 2025 --mes 12   # un mes
python scripts/validar_carga.py --anios 2025
python scripts/sincronizar_codigos_administrativos.py

# Detector
python scripts/detectar_cambios.py              # informa qué cambió, no carga nada
python scripts/detectar_cambios.py --sembrar    # registra el estado actual como cargado

# Capas 2 y 3, en orden
cd mart
python detectar_conflictos_peva.py
python construir_capa2.py
python limpiar_coordenadas_nodo_isp.py
python cargar_parroquias.py                      # --forzar para recargar el shapefile
python detectar_discrepancias_geografia_nodo.py
python aplicar_capa3.py

# SIGER_V3, en orden
cd ../siger
python probar_conexion.py --pg                       # solo lectura
python aplicar_esquema_siger.py
python cargar_siger.py --tabla todas                 # o servicios | concesionarios | titulos | facturacion
python cargar_siger.py --tabla facturacion --permitir-caida   # solo tras revisar una caída real
python validar_siger.py
python construir_cruce_obtel.py --dry-run            # recalcula y reporta sin escribir hallazgos
python construir_cruce_obtel.py
```

### 13.4 Usuarios del dashboard

```bash
cd dashboard/scripts
python gestionar_usuarios.py listar
python gestionar_usuarios.py crear --username jperez --nombre "Juan Pérez"
python gestionar_usuarios.py desactivar --username jperez
python gestionar_usuarios.py resetear-password --username jperez
```

La contraseña se pide por `getpass`, nunca por argumento. El usuario administrativo que solicita debe ser el dueño del
esquema `auth` o un superusuario, **nunca** `dashboard_auth`.

## 14. Validación y calidad de datos

### 14.1 Certificación de la carga

`scripts/validar_carga.py` certifica, para cada año o para los meses cargados:

1. Conteo de filas agregadas idéntico entre SQL Server y PostgreSQL.
2. Hash MD5 idéntico fila a fila, recalculado en origen y desde los valores guardados en destino; sin filas faltantes
   ni sobrantes, y `hash_contenido` coherente con los valores de la fila.
3. Dimensiones SCD sin versiones vigentes duplicadas.
4. Vista de consumo sin duplicados por el `JOIN` de vigencia (llave natural completa de 8 columnas).
5. Completitud: todos los ISP, PEVA y formularios de SIETEL presentes, y ninguna fila de hechos perdida entre `staging`
   y `analitico`, en todos los años.

Imprime un reporte consolidado (✅/❌), registra el resultado en `staging.control_cargas` y, ante cualquier
discrepancia, deja la tarea en rojo.

### 14.2 Invariantes del mart

La sección 17.0 de `sql/02_ddl_mart.sql` corre dentro de la transacción y revierte el refresco si falla alguna, entre
ellas: ninguna columna de imputación (17.9), panel de obligación coherente con los hechos (17.10), ningún prestador
sin reporte con participación o aporte al IHH, cobertura entre 0 y 100, y `CR2 ≤ CR4 ≤ 100`.

### 14.3 Índice de SQL Server

La extracción mensual y la huella del detector dependen de este índice, **pendiente de aplicar en producción**:

```sql
CREATE NONCLUSTERED INDEX [IX_VALineasDedicadas_Analitico]
ON [dbo].[VALineasDedicadas] (anio, periodoNumero, peva_codigo, par_codigo)
INCLUDE (periodoNombre, tipoEnlace, tipoCliente, nivelComparticion,
         portador, regional, numeroUsuarios, downLink, upLink);
```

El `INCLUDE` debe cubrir todas las columnas que proyecta `SQL_EXTRAER_HECHOS_ANIO`. Aplicarlo requiere una ventana de
mantenimiento formal con el DBA de SIETEL (ver `Instruccion_Tecnica_Indice_SIETEL_v1.3.docx`).

### 14.4 Calidad de datos conocida

**Líneas dedicadas**

- SIETEL es append-only y no deduplica (un caso aparece 4.843 veces entre 2015 y 2024 en la misma dirección). El
  pipeline tampoco deduplica en silencio.
- El campo `opera` mezcla categorías descriptivas con `SI`/`NO`/`-`: es la causa de la mayoría de conflictos del
  grupo A.
- La cadencia de reporte no es uniforme: los picos en las series reflejan prestadores que reportan trimestralmente.
- Las columnas versionables SCD son una propuesta pendiente de confirmar con Mercados.
- El mismo PEVA aparece con distinta capitalización en SIETEL; se normaliza a mayúsculas (caso CNT EP, julio de 2015).

**Geografía de nodos**

- ~18,4 % de las coordenadas no se pueden convertir; quedan marcadas con su motivo, nunca descartadas.
- Un nodo exactamente sobre un vértice compartido puede resolver a cualquiera de las dos parroquias.

**Control**

- "Prestador" en Control lista el universo nacional sin acotar por territorio (la dirección contraria sí existe).
- El umbral de variación mensual (30 %) es un punto de partida ajustable, no un límite estadístico validado.

## 15. Pruebas

**Unitarias** (sin base de datos):

```bash
pip install -r requirements.txt -r mart/requirements.txt -r dashboard/requirements.txt -r requirements-dev.txt
python -m pytest tests/
```

| Archivo                          | Cubre                                                                                     |
|----------------------------------|-------------------------------------------------------------------------------------------|
| `test_reglas.py`                 | Clasificación A/B/C, detección de cambios SCD2, redirección segura del login              |
| `test_sin_imputacion.py`         | Que `capa2` y el mart no vuelvan a rellenar huecos ni marcar imputación                    |
| `test_limpiar_coordenadas.py`    | Parser DMS e inferencia de hemisferio                                                     |
| `test_detectar_cambios.py`       | Comparación de huellas por mes y agrupación en lotes                                      |
| `test_siger_reglas.py`           | SIGER: columnas permitidas, verificación de permisos, `contrato_key`, RUC resuelto, `tipo_enlace`, hash por tipo, misma normalización de RUC que el detector |

**Integración** contra el entorno real (Capa 1):

```bash
python tests/verificar_pipeline.py --anios 2026
python tests/verificar_pipeline.py --anios 2024 2025 2026 --verbose
```

Verifica conectividad, objetos esperados de Capa 1 y delega la certificación en `validar_carga`. No cubre todavía
`dim_nodo_isp` ni los esquemas `capa2`, `calidad` y `mart`. El dashboard no tiene suite automatizada: se verifica con
datos simulados y en el navegador antes de cada entrega.

## 16. Solución de problemas

### 16.1 `Falta la variable de entorno requerida` al usar `docker compose exec`

`docker compose exec` vuelve a leer el compose y pasa al comando las variables definidas en él; sin `--env-file ../.env`
las pasa en blanco y tapan las del contenedor. Ejecutar siempre desde `docker/` con
`docker compose --env-file ../.env exec ...`.

### 16.2 `no existe la relación «staging.huella_fuente»`

El esquema no se ha aplicado desde que existe la tabla. Aplicar el esquema, sembrar la huella y reconstruir el mart:

```bash
docker compose --env-file ../.env exec airflow-scheduler python /opt/airflow/scripts/aplicar_esquema.py
docker compose --env-file ../.env exec airflow-scheduler python /opt/airflow/scripts/detectar_cambios.py --sembrar
```

Luego disparar `sietel_mart_pipeline` (ver 16.4).

### 16.3 El detector falla con `staging.huella_fuente está vacía`

Es intencional: sin huella, el detector recargaría toda la historia. Sembrarla con `--sembrar` cuando PostgreSQL esté al
día.

### 16.4 El dashboard muestra `no existe la relación «mart.vw_...»`

`aplicar_esquema` recrea `analitico.v_ultimo_periodo_reportado_detalle` con `DROP ... CASCADE`, lo que borra
`mart.vw_prestadores_sin_reportar` y `mart.vw_nodos_isp_mapa`. Mientras no se reconstruya el mart fallan: los KPI
"Total de prestadores", "Tasa de entrega de reportes" y "Nunca han reportado", la página Control (queda en blanco), el
Mapa de nodos y Discrepancias de geografía. **Solución**: disparar `sietel_mart_pipeline` y esperar a que termine en
verde. Si falla, revisar el log de `aplicar_capa3`.

### 16.5 Un rol pierde acceso a `mart` tras un refresco

`DROP SCHEMA mart CASCADE` borra los permisos. La sección 18 de `sql/02_ddl_mart.sql` los re-otorga; si un rol nuevo
no está ahí, agregarlo en esa sección (como parche inmediato, ver `sql/09_patch_regrant_eda_lector.sql`).

### 16.6 La huella o la carga tardan demasiado

Sin `IX_VALineasDedicadas_Analitico` en producción, SQL Server recorre la tabla completa (la huella tarda unos 8
minutos). Para comprobar que una consulta avanza, en SSMS:

```sql
SELECT r.session_id, r.status, r.wait_type, r.total_elapsed_time / 1000 AS segundos, r.logical_reads
FROM sys.dm_exec_requests r
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE t.text LIKE '%VALineasDedicadas%' AND r.session_id <> @@SPID;
```

### 16.7 El dashboard no muestra datos recién cargados

Confirmar que `sietel_mart_pipeline` terminó en verde. La caché se vacía en menos de un minuto cuando cambia
`mart.control_version`; si el log del dashboard muestra `No se pudo leer mart.control_version`, el mart todavía no se ha
reconstruido con la versión actual de `sql/02_ddl_mart.sql`.

## 17. Registro de cambios relevantes

Cambios que alteraron resultados o la forma de operar el sistema. El detalle está en el historial de Git y en los
comentarios de cada archivo.

| Fecha        | Cambio                                                                                                                                                                                                                         |
|--------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 08-oct-2026  | **SIGER diario con detección de cambios**: `siger_pipeline` corre a las 02:00 y recarga solo las tablas cuya huella cambió (`siger.huella_fuente`); recarga y certificación completas los domingos |
| 05-oct-2026  | **SIGER_V3**: DAG `siger_pipeline`, esquema `siger` (réplica certificada por snapshot, vistas SAI por RUC, acceso restringido por LOPDP) y `calidad.hallazgos_siger_obtel`. `scripts/config.py` parametrizado por prefijo de variables, con tiempo límite de consulta; `SQL_RUC_LIMPIO` extraído en `mart/detectar_conflictos_peva.py` (SQL idéntico) |
| 30-sep-2026  | **Detección automática y recarga por mes**: DAG `sietel_detector_cambios`, `staging.huella_fuente`, carga y validación por meses, `max_active_runs=1` e invalidación de caché con `mart.control_version`                         |
| 29-sep-2026  | **Filtro territorial sin "Nivel geográfico"** en Evolución y Concentración, y nueva sección "Cuentas por territorio"                                                                                                             |
| 29-sep-2026  | **Dominante ausente con una serie por prestador** en IHH y participación; el gráfico usa el mismo período que las tarjetas y distingue un error de "sin huella"                                                                |
| 29-sep-2026  | **Eliminación completa de la imputación (LOCF)**. IHH, CR2/CR4, líder y participación resultaron idénticos; los totales pasan a ser solo lo reportado. El panel de obligación corrige además la cobertura y el churn                |
| 28-sep-2026  | Formularios de líneas dedicadas y clasificación "sin servicio"; normalización de PEVA a mayúsculas (recuperó 2.630 filas de CNT EP descartadas por el `JOIN`); certificación de completitud hasta la vista de consumo           |
| 23-sep-2026  | Página **Prioridad de carga**                                                                                                                                                                                                   |
| 18-sep-2026  | Página **Conflictos RUC/PEVA** y puente `mart.vw_conflictos_ruc_peva` (`sql/10`)                                                                                                                                                |
| 28-sep-2026  | Revisión de seguridad: límite de intentos de login, cookie `SameSite`, cierre de acceso sin sesión a callbacks de Dash y de redirección abierta en el login; invariantes del mart bloqueantes; disparo automático del mart al terminar la Capa 1 |
| 04-sep-2026  | **Módulo SMA** (Calidad de Datos móviles) y migración a plotly 7; Calidad de Voz pausada hasta contar con las medidas reales                                                                                                   |
| 22-ago-2026  | Rendimiento del dashboard: gunicorn `gthread`, caché compartida en disco, pool de conexiones acotado                                                                                                                            |
| 21-ago-2026  | Sincronización de filtros de nodos entre páginas corregida (tres causas encadenadas en Dash Pages) y filtrado cruzado Prestador → territorio                                                                                    |
| 12-ago-2026  | Filtro de territorio de "Reporte detenido" corregido: una correlación SQL ambigua lo volvía una tautología (siempre 548 filas)                                                                                                  |
| 07-ago-2026  | `_cambio_relevante()` comparaba claves con distinta capitalización y creaba versiones SCD2 espurias en cada corrida; `dim_permiso_va_agregado` bajó de 11.655 a 1.665 filas tras `remediar_versiones_espurias_scd2.py`          |
| ago-2026     | **Geografía de nodos ISP** (limpieza de coordenadas, cruce con CONALI, mapa y discrepancias) y módulo **Control**                                                                                                              |
| 22-jul-2026  | Códigos INEC en los hechos (`sincronizar_codigos_administrativos.py` para años previos)                                                                                                                                         |

Los parches `sql/06` a `sql/10` se aplicaron en producción sin esperar un refresco completo; su contenido ya está en
los DDL principales. `07` y `08` son obsoletos desde el 29-sep-2026 y abortan si se ejecutan.

## 18. Hoja de ruta

- [ ] Aplicar `IX_VALineasDedicadas_Analitico` en el servidor de producción de SIETEL.
- [ ] Servir el dashboard por HTTPS y agregar token CSRF al login.
- [ ] Aviso por correo cuando falle un DAG.
- [ ] Revisión liviana del detector (formularios primero, meses recientes a diario, completa semanal) si la huella
      completa llega a afectar a SIETEL.
- [ ] Cerrar con Mercados la lista de columnas versionables SCD (ISP, PermisoVAgregado, NodoISP).
- [ ] Ampliar `tests/verificar_pipeline.py` a `dim_nodo_isp`, `historial_correcciones` y los esquemas `capa2`,
      `calidad` y `mart`; suite automatizada para el dashboard.
- [ ] Pantalla de revisión (escritura) de conflictos RUC/PEVA y discrepancias con `calidad_revisor`.
- [ ] Reactivar Calidad de Voz (SMA) al contar con las medidas DAX reales.
- [ ] Verificar si `mgonzalez` tiene la misma fragilidad de permisos ya corregida para `mart_user`.
- [ ] Evaluar un segundo nivel de detección de discrepancias dentro del cantón (caso Sígsig).
- [ ] Evaluar acotar "Prestador" en Control por el territorio elegido.
- [ ] Vista de auditoría de líneas potencialmente duplicadas.
- [ ] Incorporar internet móvil desde SIETEL (fuente aún no identificada).

## 19. Documentación relacionada

| Documento                                                             | Contenido                                                                 |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------|
| `Informe_Hallazgos_SIETEL.docx`                                       | Por qué se descartó `VAReporteUsuariosCuentas`; patrón append-only        |
| `Propuesta_Modificacion_SIETEL.pptx`                                  | Correcciones estructurales propuestas al equipo de SIETEL                 |
| `Especificacion_Tecnica_SIETEL.docx`                                  | Diseño SCD Tipo 2, lógica de carga, plan de migración                     |
| `Instruccion_Tecnica_Indice_SIETEL_v1.3.docx`                         | Script del índice para el DBA de producción                               |
| *Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx*   | Fuente de verdad de los roles de PostgreSQL                               |
| [`mart/data/shapefiles/parroquial/README.md`](mart/data/shapefiles/parroquial/README.md) | Atributos del shapefile de CONALI y comando de transferencia |

Proyectos hermanos: [`Zerausir/samm_pipeline`](https://github.com/Zerausir/samm_pipeline) (misma infraestructura y
versión de Airflow; origen de los patrones de certificación por hash y geoprocesamiento) y `Zerausir/tablero`
(inspiración visual del panel de opciones).

## 20. Contribución

- Trabajar en una rama por cambio (`feat/…`, `fix/…`, `refactor/…`, `docs/…`) e integrar a `main` mediante pull
  request.
- Mensajes de commit en español, con prefijo convencional (`feat:`, `fix:`, `refactor:`, `docs:`).
- Antes de abrir el PR: `python -m pytest tests/` en verde y, si el cambio toca datos, verificación contra la copia de
  SIETEL (172.20.1.74) antes de producción.
- Los cambios de esquema van en los DDL principales (`sql/01`, `sql/02`, `sql/04`), que deben seguir siendo
  idempotentes. Un parche numerado solo se justifica para aplicar algo en producción sin esperar un refresco completo.
- Documentar en este README todo cambio que altere resultados, metodología u operación.

## 21. Mantenedores y soporte

| Nombre                   | Rol                                   |
|--------------------------|---------------------------------------|
| Marcos González Auhing   | Dirección de Mercados, ARCOTEL        |
| Iván Suárez Fabara       | Dirección de Mercados, ARCOTEL        |

Dudas sobre el pipeline o el dashboard: equipo de analítica de la Dirección de Mercados. Problemas de acceso o
desempeño de SIETEL: equipo técnico de SIETEL, con `Propuesta_Modificacion_SIETEL.pptx` como referencia.

## 22. Licencia

Software de uso interno de la Agencia de Regulación y Control de las Telecomunicaciones (ARCOTEL). No se ha definido
una licencia de distribución; su uso, copia o redistribución fuera de la institución requiere autorización expresa.
