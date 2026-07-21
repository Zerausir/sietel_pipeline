# Pipeline Analítico SIETEL — Módulo Usuarios y Cuentas de Internet Fijo

Pipeline de datos históricos que extrae información de líneas dedicadas de internet fijo desde **SIETEL** (el sistema
regulatorio de ARCOTEL sobre SQL Server) y la transforma en un modelo analítico en PostgreSQL, listo para consumo en
Power BI.

Desarrollado por la **Dirección de Mercados — ARCOTEL**.

---

## Tabla de contenidos

- [Qué hace este proyecto](#qué-hace-este-proyecto)
- [Por qué existe](#por-qué-existe)
- [Arquitectura](#arquitectura)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Requisitos previos](#requisitos-previos)
- [Puesta en marcha](#puesta-en-marcha)
- [Configuración](#configuración)
- [Uso](#uso)
- [Modelo de datos](#modelo-de-datos)
- [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)
- [Validación y certificación de datos](#validación-y-certificación-de-datos)
- [Calidad de datos conocida](#calidad-de-datos-conocida)
- [Documentación relacionada](#documentación-relacionada)
- [Hoja de ruta / pendientes](#hoja-de-ruta--pendientes)
- [Dónde obtener ayuda](#dónde-obtener-ayuda)
- [Mantenedores](#mantenedores)

---

## Qué hace este proyecto

- Extrae y **agrega en el propio SQL Server** (no transfiere detalle crudo)
  los datos de `dbo.VALineasDedicadas` — la tabla de origen verdaderamente cruda de líneas dedicadas, reportada mes a
  mes por cada prestador.
- Clasifica cada línea por rango de velocidad de bajada/subida según umbrales regulatorios (ITU, OCDE, UE).
- Versiona las dimensiones `ISP` y `PermisoVAgregado` con SCD Tipo 2, para poder resolver el estado de un prestador en
  cualquier punto del histórico, aunque SIETEL solo exponga su estado *actual*.
- Certifica cada carga con un hash MD5 recalculado desde el origen —no solo verifica que la cantidad de filas coincida,
  verifica que el **valor** de cada fila coincida.
- Publica vistas de consumo en el esquema `analitico`, listas para conectarse directamente desde Power BI (DirectQuery).

## Por qué existe

`dbo.VAReporteUsuariosCuentas` (la tabla que en teoría ya resume esta información) fue descartada como fuente: es una
tabla física sin ningún proceso de cálculo auditable en el esquema de SIETEL —sin vista, trigger ni procedimiento
almacenado que explique cómo se puebla—, por lo que sus inconsistencias no son trazables al origen. Ese hallazgo está
documentado formalmente en `Informe_Hallazgos_SIETEL.docx`.

`dbo.VALineasDedicadas` sí es un dato crudo auditable: una fila por línea dedicada, por cliente, por período, reportada
directamente por el prestador. Este pipeline construye sobre esa fuente.

## Arquitectura

```
┌─────────────────────────────┐
│   SQL Server SIETEL          │  dbo.VALineasDedicadas (~282M filas / 487 GB)
│   172.20.1.38 (producción)   │  SQL Server 2008 R2 Standard Edition
│   172.20.1.74 (copia)        │
└──────────────┬───────────────┘
               │ pyodbc + ODBC Driver 18 for SQL Server
               │ GROUP BY ejecutado en SQL Server — NO se transfiere detalle crudo
               ▼
┌─────────────────────────────────────────────┐
│   Apache Airflow 3.2.2 (Docker Desktop)      │
│   airflow-webserver · airflow-scheduler      │
│   airflow-dag-processor · airflow-triggerer  │
│   airflow-metadata-db (Postgres interno)     │
└──────────────┬────────────────────────────────┘
               │ psycopg2 (execute_batch)
               ▼
┌─────────────────────────────────────────────┐
│   PostgreSQL nativo (Windows 11 host)         │
│   Base: sietel_analitico                      │
│   Esquemas: staging (tablas) · analitico (vistas) │
└──────────────┬────────────────────────────────┘
               │ DirectQuery
               ▼
        Power BI (reportes de Mercados)
```

**Por qué `pyodbc` y no `pymssql`:** el servidor SIETEL exige una renegociación TLS que FreeTDS (usado internamente por
`pymssql`) rechaza durante el handshake. El driver ODBC oficial de Microsoft —el mismo stack que usa SQL Server
Management Studio— sí negocia correctamente. El
`Dockerfile` además habilita `UnsafeLegacyRenegotiation` en OpenSSL, porque SQL Server 2008 R2 no soporta RFC 5746
(renegociación TLS segura), que OpenSSL 3.x exige por defecto.

**Por qué PostgreSQL corre nativo en el host y no en un contenedor:**
facilita backups institucionales (`pg_dump`/`pg_basebackup`) y portabilidad directa hacia la infraestructura de ARCOTEL.
Desde los contenedores de Airflow se accede vía `host.docker.internal`; desde Windows, vía
`localhost`.

## Estructura del repositorio

```
sietel_pipeline/
├── dags/
│   └── sietel_usuarios_cuentas_pipeline.py   # DAG: esquema → dimensiones → hechos → validación
├── scripts/
│   ├── config.py               # Conexiones, variables de entorno, ANIO_INICIO/FIN_HISTORICO
│   ├── aplicar_esquema.py      # Ejecuta sql/01_ddl_postgres.sql de forma idempotente
│   ├── cargar_dimensiones.py   # SCD Tipo 2: dim_isp y dim_permiso_va_agregado
│   ├── cargar_hechos_anio.py   # Extracción agregada (mes a mes) + upsert certificado
│   └── validar_carga.py        # Certificación cruzada SQL Server vs PostgreSQL
├── sql/
│   └── 01_ddl_postgres.sql     # DDL completo: tablas, índices, dimensiones, vistas
├── docker/
│   ├── Dockerfile               # Airflow + pyodbc + ODBC Driver 18 + fix TLS
│   ├── docker-compose.yml
│   └── requirements.txt
├── tests/
│   └── verificar_pipeline.py    # Pruebas de integración end-to-end
├── requirements.txt              # Para ejecutar scripts localmente, fuera de Docker
└── .env.example
```

## Requisitos previos

- Docker Desktop (con soporte de contenedores Linux) en Windows 11, o Docker Engine en Linux.
- Acceso de red al servidor SQL Server de SIETEL (puerto 1433) desde la máquina donde corre Docker.
- PostgreSQL 14+ instalado de forma nativa en el host (no en Docker).
- Usuario de SQL Server con permiso de `SELECT` sobre `dbo.VALineasDedicadas`,
  `dbo.ISP`, `dbo.PermisoVAgregado`, `dbo.Parroquia`, `dbo.Ciudad`,
  `dbo.Provincia`.
- Para modificar el índice de SQL Server en producción (172.20.1.38): acceso del DBA de SIETEL y una ventana de
  mantenimiento (ver
  [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)).

## Puesta en marcha

### 1. Preparar PostgreSQL analítico

```bash
sudo -u postgres createdb sietel_analitico
sudo -u postgres createuser sietel_etl --pwprompt
```

El esquema completo (`staging` + `analitico`) se aplica desde el propio pipeline —no hace falta correr el DDL a mano—
ver
[Uso](#uso).

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con las credenciales reales, **sin comillas alrededor de los valores** (Docker Compose no las interpreta
como bash; si las incluyes, pasan a formar parte literal del valor).

### 3. Levantar Airflow

```powershell
cd docker
docker compose --env-file ..\.env up -d
```

Verificar que los cinco servicios queden saludables:
`airflow-webserver`, `airflow-scheduler`, `airflow-dag-processor`,
`airflow-triggerer`, `airflow-metadata-db`.

### 4. Aplicar el esquema y cargar dimensiones (primera vez)

```powershell
docker compose --env-file ..\.env exec airflow-scheduler python /opt/airflow/scripts/aplicar_esquema.py
docker compose --env-file ..\.env exec airflow-scheduler python /opt/airflow/scripts/cargar_dimensiones.py
```

## Configuración

Variables de entorno (`.env`), inyectadas a los contenedores de Airflow vía
`docker-compose.yml`:

| Variable                                              | Descripción                                                    |
|-------------------------------------------------------|----------------------------------------------------------------|
| `SIETEL_SQLSERVER_HOST`                               | IP del servidor SQL Server de SIETEL (producción o copia)      |
| `SIETEL_SQLSERVER_PORT`                               | Puerto, por defecto `1433`                                     |
| `SIETEL_SQLSERVER_USER` / `SIETEL_SQLSERVER_PASSWORD` | Credenciales de SQL Server                                     |
| `SIETEL_SQLSERVER_DATABASE`                           | Nombre de la base, `SIETEL`                                    |
| `SIETEL_SQLSERVER_ODBC_DRIVER`                        | Por defecto `ODBC Driver 18 for SQL Server`                    |
| `ANALITICO_PG_HOST`                                   | `host.docker.internal` desde Docker, `localhost` desde Windows |
| `ANALITICO_PG_PORT`                                   | Puerto de PostgreSQL, por defecto `5432`                       |
| `ANALITICO_PG_USER` / `ANALITICO_PG_PASSWORD`         | Credenciales de PostgreSQL                                     |
| `ANALITICO_PG_DATABASE`                               | `sietel_analitico`                                             |
| `AIRFLOW__CORE__FERNET_KEY`                           | Cifra Connections/Variables en la metadata de Airflow          |
| `AIRFLOW__API_AUTH__JWT_SECRET`                       | Comunicación interna scheduler ↔ api-server (Airflow 3.x)      |

`AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG` se controla en
`docker-compose.yml` (no en `.env`) — limita cuántos años del histórico se cargan en paralelo, para no saturar SQL
Server con conexiones concurrentes.

`ANIO_INICIO_HISTORICO` y `ANIO_FIN_HISTORICO` se definen **únicamente** en
`scripts/config.py` — no redefinir en el DAG ni en ningún otro script.

## Uso

### Vía Airflow (recomendado para cargas completas)

1. Airflow UI → **Admin → Variables** → crear/editar `sietel_anios_a_cargar`:

   | Valor | Comportamiento |
      |---|---|
   | `historico` | Carga el rango completo `ANIO_INICIO_HISTORICO`..`ANIO_FIN_HISTORICO` |
   | `2025` | Carga solo ese año |
   | `2023,2024,2025` | Carga esa lista de años |
   | (ausente o cualquier otro valor) | Carga solo el año en curso (modo mensual regular) |

2. **DAGs** → `sietel_usuarios_cuentas_pipeline` → Trigger DAG.

El DAG corre las tareas en este orden:
`aplicar_esquema >> cargar_dimensiones >> cargar_hechos_de_anio (uno por año, en paralelo limitado) >> validar_carga`.

### Vía CLI (pruebas puntuales / smoke tests)

```powershell
# Cargar un año completo
docker compose --env-file ..\.env exec airflow-scheduler python /opt/airflow/scripts/cargar_hechos_anio.py --anio 2025

# Cargar un solo mes (smoke test de rendimiento, con desglose de tiempos)
docker compose --env-file ..\.env exec airflow-scheduler python /opt/airflow/scripts/cargar_hechos_anio.py --anio 2025 --mes 12

# Certificación cruzada de uno o más años
docker compose --env-file ..\.env exec airflow-scheduler python /opt/airflow/scripts/validar_carga.py --anios 2025
```

## Modelo de datos

**Esquema `staging`** (tablas físicas):

| Tabla                         | Contenido                                                                                                                                                  |
|-------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `va_lineas_dedicadas_resumen` | Hechos agregados: una fila por combinación única de `(peva_codigo, par_codigo, periodoNumero, anio, tipoEnlace, tipoCliente, nivelComparticion, portador)` |
| `dim_isp`                     | Dimensión ISP, versionada (SCD Tipo 2)                                                                                                                     |
| `dim_permiso_va_agregado`     | Dimensión de permisos de prestador, versionada (SCD Tipo 2)                                                                                                |
| `control_cargas`              | Auditoría de cada corrida: tipo, año, filas, estado, errores                                                                                               |

**Esquema `analitico`** (vistas de consumo para Power BI):

| Vista                                | Uso                                                                                                                                                                                                   |
|--------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `v_lineas_dedicadas_resumen`         | Serie histórica completa, con dimensiones resueltas por vigencia temporal. Solo incluye prestadores con actividad reportada.                                                                          |
| `v_ultimo_periodo_reportado_detalle` | Último período reportado por cada prestador **vigente**, cruzado con su estado administrativo actual (`opera`). Incluye prestadores vigentes sin ningún reporte histórico (`tiene_reportes = false`). |

**Columnas por rango de velocidad** (`lineas_dl_*` para bajada,
`lineas_ul_*` para subida) cuentan **líneas/cuentas**, no usuarios finales — para usuarios finales usar `total_usuarios`
(agregado general, no desglosado por rango):

| Columna         | Rango (Kbps)        | Referencia         |
|-----------------|---------------------|--------------------|
| `sin_datos`     | NULL o 0            | No reportado       |
| `menos_1mbps`   | < 1.024             | Brecha digital     |
| `1_10mbps`      | 1.024 – 10.239      | Umbral mínimo ITU  |
| `10_30mbps`     | 10.240 – 30.719     | Umbral básico OCDE |
| `30_100mbps`    | 30.720 – 102.399    | Umbral UE          |
| `100mbps_1gbps` | 102.400 – 1.048.575 | Ultra banda ancha  |
| `1gbps_o_mas`   | ≥ 1.048.576         | Gigabit            |

## Rendimiento e índice de SQL Server

`dbo.VALineasDedicadas` requiere un índice compuesto cubridor (`IX_VALineasDedicadas_Analitico`) para que la extracción
mensual sea viable — sin él, una consulta de agregación no completaba en más de 10 minutos.

```sql
CREATE NONCLUSTERED INDEX [IX_VALineasDedicadas_Analitico]
ON [dbo].[VALineasDedicadas] (anio, periodoNumero, peva_codigo, par_codigo)
INCLUDE (periodoNombre, tipoEnlace, tipoCliente, nivelComparticion,
         portador, regional, numeroUsuarios, downLink, upLink);
```

El `INCLUDE` debe cubrir **todas** las columnas que
`SQL_EXTRAER_HECHOS_ANIO` proyecta o agrupa — una versión anterior que omitía `downLink`/`upLink`/`nivelComparticion`/
`portador`/`regional` seguía forzando *key lookups* y dejaba la extracción en ~125s/mes; con el `INCLUDE`
completo baja a ~40-50s/mes para los meses de mayor volumen.

Cambiar este índice en producción (172.20.1.38) requiere una ventana de mantenimiento formal — ver
`Instruccion_Tecnica_Indice_SIETEL_v1.3.docx`.

## Validación y certificación de datos

`validar_carga.py` no solo confirma que la carga "no falló": recalcula el agregado completo desde SQL Server (mes a mes,
igual que la carga) y compara un hash MD5 por fila contra lo almacenado en PostgreSQL — certificando que el **valor** de
cada fila migrada coincide con el origen, no solo la cantidad de filas.

Chequeos adicionales en la misma tarea:

- Dimensiones SCD sin versiones vigentes duplicadas.
- Vista de consumo sin filas duplicadas por el `JOIN` de vigencia temporal.

El resultado se imprime como un reporte consolidado (✅/❌ por chequeo) y se registra en `staging.control_cargas` para
auditoría histórica.

## Calidad de datos conocida

Hallazgos documentados durante el desarrollo, relevantes para interpretar correctamente los resultados:

- **Patrón append-only sin deduplicación**: la misma línea genera una fila nueva cada mes aunque no cambie nada —
  verificado con un caso que aparece 4.843 veces entre 2015-2024 en la misma dirección. El pipeline **no deduplica**
  silenciosamente (sería alterar el dato oficial reportado sin intervención de SIETEL o del prestador); una vista de
  auditoría de duplicados queda pendiente como mejora futura, separada del dato certificado.
- **Campo `opera` con codificación heredada inconsistente**: la mayoría de permisos usa categorías descriptivas
  (`Opera Normalmente`, `Nuevo`,
  `Cancelación`, etc.), pero 9 de 1.665 registros usan una codificación antigua (`SI`/`NO`/`-`). Los 9 corresponden a
  permisos vigentes sin ninguna línea operada jamás — consistente con captura residual nunca actualizada.
- **La copia de pruebas (172.20.1.74) puede estar desactualizada respecto a producción (172.20.1.38)**: verificado un
  desfase de 325 ISPs/permisos entre ambas. Antes de una carga final, `cargar_dimensiones.py` debe correr contra
  producción, no asumir que correrlo contra la copia es suficiente.

## Documentación relacionada

| Documento                                     | Contenido                                                          |
|-----------------------------------------------|--------------------------------------------------------------------|
| `Informe_Hallazgos_SIETEL.docx`               | Por qué se descartó `VAReporteUsuariosCuentas`, patrón append-only |
| `Propuesta_Modificacion_SIETEL.pptx`          | Propuesta de correcciones estructurales para el equipo de SIETEL   |
| `Especificacion_Tecnica_SIETEL.docx`          | Diseño SCD Tipo 2, lógica de carga, plan de migración              |
| `Instruccion_Tecnica_Indice_SIETEL_v1.3.docx` | Script de índice listo para el DBA de producción                   |

Patrones de diseño (certificación de contenido vía hash, carga por lotes con `execute_batch`) tomados como referencia de
[`Zerausir/samm_pipeline`](https://github.com/Zerausir/samm_pipeline), un pipeline hermano ya probado en producción.

## Hoja de ruta / pendientes

- [ ] Aplicar el índice `IX_VALineasDedicadas_Analitico` (v1.3) en producción (172.20.1.38).
- [ ] Correr `cargar_dimensiones.py` contra producción antes de la carga histórica final.
- [ ] Vista de auditoría de líneas potencialmente duplicadas (separada del dato certificado).
- [ ] Confirmar con SIETEL el significado de los valores heredados de `opera` (`SI`/`NO`/`-`).
- [ ] Incorporar datos de internet móvil (fuente aún no identificada en SIETEL).
- [ ] Análisis geoespacial cruzando `par_codigo` con `sectores_anonimizados.gpkg`.

## Dónde obtener ayuda

Para dudas sobre este pipeline, contactar al equipo de analítica de la Dirección de Mercados. Para problemas de acceso o
desempeño del propio SIETEL, canalizar a través de `Propuesta_Modificacion_SIETEL.pptx` y el equipo técnico de SIETEL.

## Mantenedores

- **Iván Suárez Fabara** — Dirección de Mercados, ARCOTEL.