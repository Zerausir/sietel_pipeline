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
- [Configuración](#configuración)
- [Uso](#uso)
- [Modelo de datos](#modelo-de-datos)
- [Códigos administrativos y sincronización](#códigos-administrativos-y-sincronización)
- [Historial de correcciones](#historial-de-correcciones)
- [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)
- [Validación y certificación de datos](#validación-y-certificación-de-datos)
- [Calidad de datos conocida](#calidad-de-datos-conocida)
- [Pruebas de integración](#pruebas-de-integración)
- [Documentación relacionada](#documentación-relacionada)
- [Hoja de ruta / pendientes](#hoja-de-ruta--pendientes)
- [Dónde obtener ayuda](#dónde-obtener-ayuda)
- [Mantenedores](#mantenedores)

---

## Qué hace este proyecto

- Extrae y **agrega en el propio SQL Server** (no transfiere detalle crudo) los datos de `dbo.VALineasDedicadas` — la
  tabla de origen verdaderamente cruda de líneas dedicadas, reportada mes a mes por cada prestador.
- Particiona la extracción **mes a mes** dentro de cada año, no en una sola consulta anual, para mantener acotado el
  volumen en memoria y el radio de un eventual fallo.
- Clasifica cada línea por rango de velocidad de bajada/subida según umbrales regulatorios (ITU, OCDE, UE).
- Agrega códigos administrativos (`codigo_provincia`, `codigo_ciudad`, `codigo_parroquia`) para cruce con las tablas del
  INEC.
- Versiona las dimensiones `ISP` y `PermisoVAgregado` con SCD Tipo 2, para poder resolver el estado de un prestador en
  cualquier punto del histórico, aunque SIETEL solo exponga su estado *actual*.
- Certifica cada carga con un hash MD5 recalculado desde el origen — no solo verifica que la cantidad de filas coincida,
  verifica que el **valor** de cada fila coincida.
- Registra automáticamente (vía trigger de base de datos) cuándo el contenido certificado de una fila cambia entre una
  carga y otra.
- Publica vistas de consumo en el esquema `analitico`, listas para conectarse directamente desde Power BI.

## Por qué existe

`dbo.VAReporteUsuariosCuentas` (la tabla que en teoría ya resume esta información) fue descartada como fuente: es una
tabla física sin ningún proceso de cálculo auditable en el esquema de SIETEL — sin vista, trigger ni procedimiento
almacenado que explique cómo se puebla —, por lo que sus inconsistencias no son trazables al origen. Ese hallazgo está
documentado formalmente en `Informe_Hallazgos_SIETEL.docx`.

`dbo.VALineasDedicadas` sí es un dato crudo auditable: una fila por línea dedicada, por cliente, por período, reportada
directamente por el prestador. Este pipeline construye sobre esa fuente.

## Arquitectura

```
[SQL Server SIETEL — dbo.VALineasDedicadas]
        │  pyodbc + ODBC Driver 18 for SQL Server
        │  Fix OpenSSL UnsafeLegacyRenegotiation (SQL Server 2008 R2 no soporta RFC 5746)
        │  GROUP BY ejecutado en SQL Server, particionado por mes — NO se transfiere detalle crudo
        ▼
[Apache Airflow 3.3.0 / Python 3.14 — Docker, sobre VMs RHEL]
        │  LocalExecutor · api-server (puerto externo configurable) · scheduler
        │  dag-processor · triggerer
        │  Metadata de Airflow: PostgreSQL bare-metal (base separada, NO en un contenedor propio)
        ▼
[PostgreSQL — base sietel_analitico]
        │  Esquema staging: tablas físicas (hechos, dimensiones SCD, control de cargas, historial de correcciones)
        │  Esquema analitico: vistas de consumo
        ▼
Power BI (reportes de la Dirección de Mercados)
```

**Por qué `pyodbc` y no `pymssql`:** el servidor SIETEL exige una negociación TLS que FreeTDS (usado internamente por
`pymssql`) rechaza durante el handshake — confirmado con TDSDUMP, error "login packet rejected". El driver ODBC oficial
de Microsoft (el mismo stack que usa SQL Server Management Studio) sí negocia correctamente.

**Por qué el fix de OpenSSL:** SQL Server 2008 R2 no soporta RFC 5746 (renegociación TLS segura), que OpenSSL 3.x exige
por defecto. Sin el fix, la conexión falla con `SSL routines::unsafe legacy renegotiation disabled`. El fix se aplica
solo dentro del contenedor de este pipeline — no debe extenderse nunca a un contenedor compartido con otro pipeline.

**Por qué la metadata de Airflow no corre en un contenedor Postgres propio:** vive en la instancia PostgreSQL bare-metal
ya existente, en una base separada — facilita backups institucionales y evita levantar una instancia de base de datos
adicional solo para metadata.

## Estructura del repositorio

```
sietel_pipeline/
├── dags/
│   └── sietel_usuarios_cuentas_pipeline.py   # DAG: esquema → dimensiones → años → hechos (mapeado) → validación
├── scripts/
│   ├── config.py                             # Conexiones, ANIO_INICIO_HISTORICO=2011 / ANIO_FIN_HISTORICO=2025
│   ├── aplicar_esquema.py                    # Ejecuta sql/01_ddl_postgres.sql de forma idempotente
│   ├── cargar_dimensiones.py                 # SCD Tipo 2: dim_isp y dim_permiso_va_agregado
│   ├── cargar_hechos_anio.py                 # Extracción agregada mes a mes + upsert certificado por hash
│   ├── sincronizar_codigos_administrativos.py# Backfill idempotente de códigos INEC, standalone (no está en el DAG)
│   └── validar_carga.py                      # Certificación cruzada SQL Server vs PostgreSQL
├── sql/
│   └── 01_ddl_postgres.sql                   # DDL completo: tablas, índices, dimensiones, vistas, trigger
├── docker/
│   ├── Dockerfile                            # Airflow 3.3.0/Python 3.14 + pyodbc + ODBC Driver 18 + fix TLS
│   └── docker-compose.yml
├── tests/
│   └── verificar_pipeline.py                 # Pruebas de integración end-to-end contra el entorno real
├── requirements.txt                          # Para ejecutar scripts localmente, fuera de Docker
└── .gitignore
```

> **Nota:** no existe `docker/requirements.txt` ni `.env.example` en este repositorio — las dependencias del
> contenedor se instalan directamente en el `Dockerfile`, y las variables de entorno se documentan en la sección
> [Configuración](#configuración) en vez de en un archivo de ejemplo versionado.

## Requisitos previos

- Docker (Compose v2) sobre el host/VM donde corre este pipeline.
- Acceso de red al servidor SQL Server de SIETEL (puerto 1433).
- Instancia PostgreSQL accesible tanto para la metadata de Airflow como para la base analítica `sietel_analitico`
  (pueden ser bases separadas en la misma instancia).
- Usuario de SQL Server con permiso de `SELECT` sobre `dbo.VALineasDedicadas`, `dbo.ISP`, `dbo.PermisoVAgregado`,
  `dbo.Parroquia`, `dbo.Ciudad`, `dbo.Provincia`.
- Ventana de mantenimiento formal y acceso del DBA de SIETEL para modificar índices en el servidor de producción (ver
  [Rendimiento e índice de SQL Server](#rendimiento-e-índice-de-sql-server)).

## Configuración

Variables de entorno requeridas por `scripts/config.py` (sin valor por defecto — el script falla explícitamente si
faltan):

| Variable                                              | Descripción                            |
|-------------------------------------------------------|----------------------------------------|
| `SIETEL_SQLSERVER_HOST`                               | Host del servidor SQL Server de SIETEL |
| `SIETEL_SQLSERVER_DATABASE`                           | Base de datos, `SIETEL`                |
| `SIETEL_SQLSERVER_USER` / `SIETEL_SQLSERVER_PASSWORD` | Credenciales de SQL Server             |
| `ANALITICO_PG_HOST`                                   | Host de PostgreSQL analítico           |
| `ANALITICO_PG_USER` / `ANALITICO_PG_PASSWORD`         | Credenciales de PostgreSQL             |
| `ANALITICO_PG_DATABASE`                               | `sietel_analitico`                     |

Con valor por defecto si no se definen:

| Variable                       | Default                         |
|--------------------------------|---------------------------------|
| `SIETEL_SQLSERVER_PORT`        | `1433`                          |
| `SIETEL_SQLSERVER_ODBC_DRIVER` | `ODBC Driver 18 for SQL Server` |
| `ANALITICO_PG_PORT`            | `5432`                          |
| `LOG_LEVEL`                    | `INFO`                          |

Adicionalmente, `docker-compose.yml` requiere variables propias de Airflow (`AIRFLOW__CORE__FERNET_KEY`,
`AIRFLOW__API_AUTH__JWT_SECRET`, credenciales `AIRFLOW_METADATA_PG_*` de la base de metadata bare-metal, y
`_AIRFLOW_WWW_USER_USERNAME`), inyectadas al contenedor vía el mismo mecanismo de entorno.

`ANIO_INICIO_HISTORICO` y `ANIO_FIN_HISTORICO` se definen **únicamente** en `scripts/config.py` (2011 y 2025
respectivamente) — no se redefinen en el DAG ni en ningún otro script, para evitar la divergencia entre copias que ya
ocurrió antes.

`AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG=1` se controla en `docker-compose.yml` — limita la concurrencia para no saturar
SQL Server mientras el índice compuesto no exista en producción.

## Uso

### Vía Airflow (recomendado para cargas completas)

1. Airflow UI → **Admin → Variables** → crear/editar `sietel_anios_a_cargar`:

   | Valor | Comportamiento |
      |---|---|
   | `historico` | Carga el rango completo `ANIO_INICIO_HISTORICO`..`ANIO_FIN_HISTORICO` |
   | `2025` | Carga solo ese año |
   | `2023,2024,2025` | Carga esa lista de años |
   | (ausente o cualquier otro valor) | Carga solo el año en curso |

2. **DAGs** → `sietel_usuarios_cuentas_pipeline` → Trigger DAG (`schedule=None`: siempre manual).

El DAG corre: `aplicar_esquema >> cargar_dimensiones >> obtener_anios_a_cargar >> cargar_hechos_de_anio (uno por año,
dynamic task mapping) >> validar_carga`.

### Vía CLI (pruebas puntuales / smoke tests)

```bash
# Aplicar esquema y cargar dimensiones (primera vez)
python scripts/aplicar_esquema.py
python scripts/cargar_dimensiones.py

# Cargar un año completo (itera los 12 meses internamente)
python scripts/cargar_hechos_anio.py --anio 2025

# Cargar un solo mes — smoke test de rendimiento, con desglose de tiempos SQL Server vs Postgres
python scripts/cargar_hechos_anio.py --anio 2025 --mes 12

# Certificación cruzada de uno o más años
python scripts/validar_carga.py --anios 2025

# Backfill de códigos administrativos (para años cargados antes del cambio del 22-jul-2026)
python scripts/sincronizar_codigos_administrativos.py
```

## Modelo de datos

**Esquema `staging`** (tablas físicas):

| Tabla                         | Contenido                                                                                                                                                  |
|-------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `va_lineas_dedicadas_resumen` | Hechos agregados: una fila por combinación única de `(peva_codigo, par_codigo, periodoNumero, anio, tipoEnlace, tipoCliente, nivelComparticion, portador)` |
| `dim_isp`                     | Dimensión ISP, versionada (SCD Tipo 2)                                                                                                                     |
| `dim_permiso_va_agregado`     | Dimensión de permisos de prestador, versionada (SCD Tipo 2)                                                                                                |
| `control_cargas`              | Auditoría de cada corrida: tipo, año, filas, estado, errores                                                                                               |
| `historial_correcciones`      | Snapshot (JSONB) de cada fila de hechos cuya certificación de contenido cambió entre una carga y otra                                                      |

**Esquema `analitico`** (vistas de consumo para Power BI):

| Vista                                | Uso                                                                                                                                                                                                   |
|--------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `v_lineas_dedicadas_resumen`         | Serie histórica completa, con dimensiones resueltas por vigencia temporal. Solo prestadores con actividad reportada.                                                                                  |
| `v_ultimo_periodo_reportado_detalle` | Último período reportado por cada prestador **vigente**, cruzado con su estado administrativo actual (`opera`). Incluye prestadores vigentes sin ningún reporte histórico (`tiene_reportes = false`). |

**Columnas por rango de velocidad** (`lineas_dl_*` para bajada, `lineas_ul_*` para subida) cuentan **líneas/cuentas**,
no usuarios finales — para usuarios finales usar `total_usuarios` (agregado general, no desglosado por rango):

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
`scripts/sincronizar_codigos_administrativos.py`
trae el mapeo `par_codigo → códigos` una sola vez (tabla pequeña, no requiere volver a agregar `VALineasDedicadas`) y
actualiza las filas existentes. Es idempotente y reutilizable; no está cableado al DAG, se invoca por CLI bajo demanda.
Los años cargados **después** del cambio ya traen los códigos desde el primer INSERT.

Este backfill **no** modifica `hash_contenido` ni genera entradas en `historial_correcciones` — no es una corrección de
contenido certificado, es completar metadata administrativa.

## Historial de correcciones

`staging.historial_correcciones`, poblada por el trigger `trg_registrar_correccion_resumen` (`BEFORE UPDATE` sobre
`va_lineas_dedicadas_resumen`), registra un snapshot completo (JSONB) de la fila anterior cada vez que
`hash_contenido` cambia entre una carga y otra — sin importar qué script disparó el `UPDATE`.

**Importante:** esta tabla no distingue una corrección real de un prestador (cambió su reporte de un período ya cerrado)
de un reprocesamiento propio (se corrigió un bug de fórmula y se recargó el año) — ambos casos generan una entrada. Esa
distinción de causa vive en `staging.control_cargas` y en el historial de Git de por qué se relanzó ese año, no en esta
tabla.

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

`validar_carga.py` recalcula el agregado completo desde SQL Server — mes a mes, igual que la carga — y compara un hash
MD5 por fila contra lo almacenado en PostgreSQL, certificando que el **valor** de cada fila migrada coincide con el
origen, no solo la cantidad de filas.

Chequeos adicionales en la misma tarea:

- Dimensiones SCD sin versiones vigentes duplicadas.
- Vista de consumo (`v_lineas_dedicadas_resumen`) sin filas duplicadas por el `JOIN` de vigencia temporal, verificado
  agrupando por la llave natural completa de 8 columnas.

El resultado se imprime como reporte consolidado (✅/❌ por chequeo) y se registra en `staging.control_cargas`.

## Calidad de datos conocida

- **Patrón append-only sin deduplicación**: la misma línea genera una fila nueva cada mes aunque no cambie nada —
  verificado con un caso que aparece 4.843 veces entre 2015-2024 en la misma dirección. El pipeline **no deduplica**
  silenciosamente (sería alterar el dato oficial reportado sin intervención de SIETEL o del prestador); una vista de
  auditoría de duplicados queda pendiente como mejora futura, separada del dato certificado.
- **Campo `opera` con codificación heredada inconsistente**: la mayoría de permisos usa categorías descriptivas
  (`Opera Normalmente`, `Nuevo`, `Cancelación`, etc.), pero 9 de 1.665 registros usan una codificación antigua (`SI`/
  `NO`/`-`) — consistente con captura residual nunca actualizada, pendiente de confirmar con SIETEL.
- **La copia de pruebas puede estar desactualizada respecto a producción**: verificado un desfase de 325 ISPs/permisos
  entre ambas en una comparación puntual. Antes de una carga final, `cargar_dimensiones.py` debe correr contra
  producción.
- **Lista de columnas versionables SCD no cerrada formalmente**: `COLUMNAS_VERSIONABLES_ISP` y
  `COLUMNAS_VERSIONABLES_PERMISO` en `cargar_dimensiones.py` son, según el propio código, una propuesta inicial
  pendiente de confirmar con el área de Mercados.

## Pruebas de integración

`tests/verificar_pipeline.py` no es una suite de unit tests con mocks — valida contra el entorno real:

```bash
python tests/verificar_pipeline.py --anios 2026
python tests/verificar_pipeline.py --anios 2024 2025 2026 --verbose
```

Verifica, en orden: conectividad a ambas bases, existencia de las tablas/vistas esperadas del esquema vigente, y delega
la certificación cruzada en `validar_carga.validar_anios()` (la misma función que corre en la tarea del DAG).

> **Cobertura conocida como incompleta:** las listas `TABLAS_ESPERADAS` y `VISTAS_ESPERADAS` de este script no
> incluyen `staging.historial_correcciones` ni `analitico.v_ultimo_periodo_reportado_detalle` todavía.

## Documentación relacionada

| Documento                                     | Contenido                                                          |
|-----------------------------------------------|--------------------------------------------------------------------|
| `Informe_Hallazgos_SIETEL.docx`               | Por qué se descartó `VAReporteUsuariosCuentas`, patrón append-only |
| `Propuesta_Modificacion_SIETEL.pptx`          | Propuesta de correcciones estructurales para el equipo de SIETEL   |
| `Especificacion_Tecnica_SIETEL.docx`          | Diseño SCD Tipo 2, lógica de carga, plan de migración              |
| `Instruccion_Tecnica_Indice_SIETEL_v1.3.docx` | Script de índice listo para el DBA de producción                   |

Patrones de diseño (certificación de contenido vía hash, carga por lotes con `execute_batch`) tomados como referencia
de [`Zerausir/samm_pipeline`](https://github.com/Zerausir/samm_pipeline), un pipeline hermano con el que se comparte
infraestructura de VMs y versión de Airflow.

## Hoja de ruta / pendientes

- [ ] Aplicar el índice `IX_VALineasDedicadas_Analitico` en el servidor de producción de SIETEL.
- [ ] Correr `cargar_dimensiones.py` contra producción antes de cualquier carga histórica final.
- [ ] Vista de auditoría de líneas potencialmente duplicadas (separada del dato certificado).
- [ ] Confirmar con SIETEL el significado de los valores heredados de `opera` (`SI`/`NO`/`-`).
- [ ] Cerrar formalmente con el área de Mercados la lista de columnas versionables SCD de ISP y PermisoVAgregado.
- [ ] Ampliar `tests/verificar_pipeline.py` para cubrir `historial_correcciones` y `v_ultimo_periodo_reportado_detalle`.
- [ ] Documentar las variables `AIRFLOW_METADATA_PG_*` en un archivo de referencia de configuración.
- [ ] Incorporar datos de internet móvil (fuente aún no identificada en SIETEL).
- [ ] Análisis geoespacial cruzando `par_codigo` con datos de sectores censales.

## Dónde obtener ayuda

Para dudas sobre este pipeline, contactar al equipo de analítica de la Dirección de Mercados. Para problemas de acceso o
desempeño del propio SIETEL, canalizar a través de `Propuesta_Modificacion_SIETEL.pptx` y el equipo técnico de SIETEL.

## Mantenedores

- **Iván Suárez Fabara** — Dirección de Mercados, ARCOTEL.