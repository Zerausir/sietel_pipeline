# Pipeline Analítico SIETEL — Módulo Usuarios y Cuentas

Carga datos del sistema SIETEL (SQL Server, ARCOTEL) hacia un servidor
PostgreSQL analítico, orquestado con Apache Airflow 3.x.

## Arquitectura

```
[SQL Server SIETEL] --(pymssql, red directa)--> [Airflow en Docker] --> [PostgreSQL nativo]
                                                       |
                                          api-server, scheduler,
                                          dag-processor, triggerer
```

- **PostgreSQL analítico**: corre **nativo en el host** (no en Docker), para
  facilitar backups institucionales (`pg_dump`/`pg_basebackup`) y portabilidad
  directa a las VMs del data center de ARCOTEL.
- **Airflow**: corre en Docker (4 servicios: api-server, scheduler,
  dag-processor, triggerer — arquitectura de Airflow 3.x), con su propio
  PostgreSQL de metadata interno, separado del PostgreSQL analítico.
- **Conexión a SQL Server**: vía `pymssql` (no requiere instalar el driver
  ODBC de Microsoft a nivel de sistema operativo).

## Estructura del proyecto

```
sietel_pipeline/
├── dags/
│   └── sietel_usuarios_cuentas_pipeline.py   # DAG de Airflow
├── scripts/
│   ├── config.py                  # conexiones, lee variables de entorno
│   ├── cargar_dimensiones.py      # SCD Tipo 2: ISP, PermisoVAgregado
│   └── cargar_hechos_anio.py      # carga de hechos, un año a la vez
├── sql/
│   └── 01_ddl_postgres.sql        # DDL completo de PostgreSQL
├── docker/
│   ├── Dockerfile                 # imagen de Airflow + pymssql + psycopg2
│   ├── docker-compose.yml
│   └── requirements.txt
├── tests/
│   └── verificar_pipeline.py      # verificación end-to-end del pipeline
├── requirements.txt               # para ejecutar scripts localmente (fuera de Docker)
└── .env.example
```

## Puesta en marcha

### 1. Preparar PostgreSQL analítico (nativo, en el host)

```bash
sudo -u postgres createdb sietel_analitico
sudo -u postgres createuser sietel_etl --pwprompt
sudo -u postgres psql -d sietel_analitico -f sql/01_ddl_postgres.sql
```

Otorgar los permisos necesarios al usuario `sietel_etl` sobre los esquemas
`staging` y `analitico` según la política de seguridad de tu institución.

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` con las credenciales reales de SQL Server y PostgreSQL, **sin
comillas alrededor de los valores** (Docker Compose no las interpreta como
bash; si las incluyes pasan a ser parte literal del valor).

Generar las dos claves obligatorias de Airflow 3.x y pegarlas en `.env`:

```powershell
# Fernet key (cifra Connections/Variables en la base de metadata)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# JWT secret (comunicación interna scheduler <-> api-server)
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[System.Convert]::ToBase64String($bytes)
```

### 3. Levantar Airflow

```bash
cd docker
docker compose up --build -d
```

Airflow 3.x usa **SimpleAuthManager** (no Flask-AppBuilder): el usuario
admin se define vía `_AIRFLOW_WWW_USER_USERNAME` en el `.env`, sin que haga
falta el comando `airflow users create` de la era 2.x. Verificar que todos
los servicios quedaron `running`:

```bash
docker compose ps
```

`airflow-init` debe aparecer como `exited (0)` — es una tarea de un solo
uso (`airflow db migrate`), eso es esperado.

Con SimpleAuthManager, Airflow genera automáticamente la contraseña del
usuario admin en el primer arranque y la imprime en los logs del servicio
api-server (aquí llamado `airflow-webserver` por compatibilidad con el
nombre de comando):

```bash
docker compose logs airflow-webserver | grep -i "password"
```

> La contraseña cambia si el contenedor se recrea desde cero; un `restart`
> simple la conserva.

### 4. Carga histórica inicial (2011-2026)

En la UI de Airflow, ir a **Admin > Variables** y crear:
- Key: `sietel_anios_a_cargar`
- Value: `historico`

Luego disparar manualmente el DAG `sietel_usuarios_cuentas_pipeline`. Esto
cargará las dimensiones una vez y los 16 años de hechos en paralelo
(limitado a 4 tareas concurrentes, ver nota de rendimiento más abajo).

Una vez completada la carga histórica, **eliminar o cambiar la variable**
`sietel_anios_a_cargar` a cualquier otro valor (o eliminarla) para que las
corridas mensuales subsecuentes solo carguen el año en curso.

### 5. Verificar el pipeline

```bash
pip install -r requirements.txt
python tests/verificar_pipeline.py --anio 2026 --verbose
```

## Decisiones de diseño relevantes

- **Nombres de columna**: las tablas de `staging` usan los nombres exactos
  de SQL Server (sin traducir). El renombrado a términos de negocio para
  la app visual se hace en una capa posterior, no en este pipeline.
- **Dimensiones versionadas (SCD Tipo 2)**: `ISP` y `PermisoVAgregado` se
  versionan solo en las columnas listadas en `COLUMNAS_VERSIONABLES_ISP` /
  `COLUMNAS_VERSIONABLES_PERMISO` dentro de `cargar_dimensiones.py`. Esta
  lista es una propuesta inicial del equipo técnico pendiente de validación
  con el área de Mercados (ver documento "Propuesta de Historizacion -
  Validacion con Mercados").
- **Limitación del histórico**: SIETEL solo expone el estado ACTUAL de ISP
  y PermisoVAgregado. No existe forma de recuperar el valor histórico real
  de `isp_nombre`/`isp_ruc`/`opera` anterior al momento en que este pipeline
  empezó a correr. La vista `analitico.v_usuarios_cuentas` documenta esta
  limitación en su comentario SQL.

## Nota de rendimiento

`VAReporteUsuariosCuentas` no tiene índices no clúster en SQL Server (ver
análisis previo: ~35,800 lecturas lógicas para extraer un solo mes/año, con
escaneo completo de tabla). `AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG` se
fijó en `4` deliberadamente para no lanzar las 16 cargas anuales en paralelo
sin control y saturar el servidor de SIETEL. Se recomienda gestionar con el
área dueña de la base de datos la creación de índices sobre
`(anio, mesNumero)`, `peva_codigo` y `par_codigo` en esa tabla — ver
recomendación detallada entregada previamente al equipo técnico.
