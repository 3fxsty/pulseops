# PulseOps

Plataforma de monitorización de webs y APIs: comprueba periódicamente si responden, cuánto tardan y guarda el historial para calcular su disponibilidad (uptime). Proyecto de portfolio backend/DevOps de Toni Correa.

---

## Cómo trabajamos (léelo antes de hacer nada)

### Roles
- **Toni es el arquitecto.** Investiga, decide herramientas, diseño y alcance. Tiene la última palabra en cada decisión.
- **Claude es quien programa.** Escribe todo el código, la configuración y los tests, y explica cada pieza.
- Toni **no necesita entender el código línea a línea**, pero **sí debe entender y poder defender cada decisión** (por qué esta herramienta, para qué sirve esta pieza). Ese es el objetivo de aprendizaje.

### Reglas para Claude
1. **Nunca empieces una fase sin que Toni la haya aprobado.** Primero se investiga y se decide; después se construye.
2. **Ante cualquier decisión de diseño o de herramienta, para y pregunta.** Presenta 2-4 opciones con pros y contras y tu recomendación justificada; la elección es de Toni.
3. **Explica con palabras sencillas**, con analogías si ayudan. Usa tecnicismos solo cuando hagan falta, y entonces explícalos.
4. Al terminar algo, resume en pocas líneas **qué hace cada pieza a nivel de arquitectura**, no de sintaxis.
5. **Toda decisión aprobada se registra en `docs/decisions.md`**, en inglés (formato ADR: contexto, opciones, decisión, motivo).
6. No avances a la siguiente fase hasta que la actual cumpla su criterio de "terminada" y Toni lo haya probado.
7. **Este archivo es la fuente de verdad del proyecto y debe estar siempre al día.** Cada sesión nueva empieza leyéndolo, así que tiene que reflejar el estado real sin depender de conversaciones anteriores:
   - **En cuanto se detecte un cambio, se actualiza aquí en ese momento**, no al final de la fase. Por ejemplo: una herramienta sustituida, una decisión nueva, una regla de negocio modificada, una tarea pendiente o algo que haya que hacer en una fase futura.
   - Si un cambio afecta a varias secciones (stack, arquitectura, roadmap…), se corrigen todas.
   - Lo que quede pendiente para más adelante se apunta en "Estado actual" o en la fase correspondiente del roadmap, para que se sepa que hay que hacerlo.
   - Al cerrar cada fase se revisa "Estado actual" completo.
8. **Al empezar cada fase nueva, entra en modo plan** antes de escribir código. En ese plan, explícale a Toni:
   - qué tiene que investigar y por qué importa cada tema;
   - qué decisiones tiene que dejar claras antes de construir, con las opciones que conviene comparar;
   - qué se va a construir y cuál es el criterio de "terminada".
9. **Evalúa cada opción por lo que aporta a PulseOps, no por su popularidad.** La popularidad solo sirve para desempatar. Si se descarta algo, explica por qué no compensa ahora y cuándo convendría reevaluarlo.
10. **Evalúa la seguridad en cada decisión, también a futuro.** Una mala decisión hoy puede costar caro cuando ya haya datos y usuarios. Las reglas permanentes están en la sección "Seguridad".
11. **Revisa a mano cada migración autogenerada antes de aplicarla** y avisa de cualquier posible pérdida de datos. Por ejemplo, Alembic interpreta un renombrado como borrar + crear.
12. **Cada recomendación a Toni debe incluir:**
    - por qué esta opción y por qué no las alternativas;
    - su punto débil;
    - si es **fácil o difícil de cambiar después**. Señala explícitamente las decisiones difíciles de revertir (rutas de la API, formato de errores, identificadores, esquema de datos), que son las que más atención merecen.

    Explica también los conceptos necesarios para que Toni pueda cuestionar la recomendación.
13. **Verifica con tests el comportamiento de las librerías en lugar de suponerlo.** Ejemplo: `ipaddress.is_global` da como públicas direcciones multicast, NAT64 e IPv4-compatible (`::/96`).

### El ciclo de cada fase
0. **Planificar** (modo plan): Claude explica qué hay que investigar y decidir en la fase.
1. **Investigar**: qué necesitamos y qué opciones existen.
2. **Decidir**: Toni elige; se apunta en `docs/decisions.md`.
3. **Construir**: Claude programa en una rama de la fase (`phase-N-name`).
4. **Verificar**: tests en verde + Toni lo prueba (Swagger, terminal o lo que toque).
5. **Cerrar**: Pull Request hacia `main`, Toni lo revisa y se fusiona.

---

## Stack

| Pieza | Herramienta | Función |
|---|---|---|
| Lenguaje | Python 3.12+ | Todo el backend |
| Proyecto y dependencias | uv | Dependencias, entornos virtuales y versión de Python |
| API | FastAPI | Gestión de monitores y consulta de estado; Swagger automático |
| Cliente HTTP | httpx2 (async, ≥ 2.13.1) | Hace las comprobaciones y mide el tiempo de respuesta (sustituye a httpx, ver ADR-008) |
| Cola de tareas | ArdiQ | Programa y ejecuta los checks en segundo plano (workers) |
| Broker | Valkey | Memoria rápida donde ArdiQ guarda la cola (confirmado con `ardiq doctor`, ver ADR-007) |
| Base de datos | PostgreSQL 18 | Monitores, historial de checks, incidentes (18 es necesario para `uuidv7()`) |
| ORM y migraciones | SQLAlchemy 2 (async) + Alembic | Acceso a la BD y cambios de esquema |
| Driver de PostgreSQL | asyncpg | Conexión async con el protocolo binario de PostgreSQL (ADR-009) |
| Configuración | pydantic-settings | Lee y valida las variables de entorno; secretos como `SecretStr` (ADR-013) |
| Tests | pytest | Tests automáticos |
| Lint y formato | Ruff | Revisión y formato de código |
| CI/CD | GitHub Actions | Lint + tests en cada push |
| Contenedores | Docker + Docker Compose | Levantar todos los servicios juntos |
| Interfaz | Swagger (MVP) → **pendiente**: Grafana y/o HTMX | Ver el estado |
| Alertas | Bot de Telegram (post-MVP) | Avisar de caídas |
| Proxy inverso | **pendiente**: Nginx o Caddy | Entrada desde internet + HTTPS |
| Servidor | VPS (Hetzner) | Producción |

### Notas sobre ArdiQ
- Cola de tareas con núcleo en Rust, async, sobre Redis Streams + Lua. Versión de referencia: **1.2.0** (oct 2026). Docs: https://ardiq.bytay.dev · Repo: https://github.com/17tayyy/ardiq
- **El autor es amigo de Toni**: si algo falla o falta, se puede preguntar directamente y abrir issues/PRs en su repo (suma al portfolio).
- Elegido frente a Celery, Taskiq y ARQ por: async nativo, poca memoria, cron/reintentos/dead letter queue incluidos y soporte directo del autor.
- **Aislar ArdiQ en su propio módulo** (p. ej. `pulseops/queue/`) para poder sustituirlo sin tocar el resto.
- Funciones a aprovechar: `@app.cron` con `coalesce=True` (no acumular checks atrasados), `ardiq doctor` (comprobar el broker), `ardiq status`, `app.metrics()` (y el endpoint de Prometheus previsto en 1.3, útil para Grafana).
- Entrega "al menos una vez": las tareas deben poder ejecutarse dos veces sin causar problemas (idempotentes).

### Valkey vs Redis
ArdiQ solo usa funciones presentes en Redis 7.2 (base de Valkey), así que debería funcionar con ambos, pero no está probado oficialmente. **Plan:** en la Fase 0, levantar Valkey en Docker Compose y ejecutar `ardiq doctor`. Si pasa → Valkey. Si falla → Redis (cambio de una línea) y avisar al autor.

---

## Seguridad (reglas permanentes)

- **SQL:** siempre con SQLAlchemy y parámetros. **Prohibido** concatenar texto o usar f-strings para construir SQL. Los campos de ordenación y filtro que lleguen del usuario se eligen de una lista cerrada.
- **Ruff** con las reglas "S" (flake8-bandit) activas.
- **Mínimo privilegio en la BD** (ADR-014). Hay tres roles:
  - `postgres`: superusuario, solo para administrar; la app nunca lo usa.
  - `pulseops_owner`: dueño del esquema, no es superusuario; solo lo usan las migraciones.
  - `pulseops_app`: lo usan la API y el worker; solo trabaja con filas (SELECT, INSERT, UPDATE, DELETE).
- **Valkey** con contraseña. Los puertos de PostgreSQL y Valkey no se publican fuera de Docker; si hace falta en local, solo en `127.0.0.1`.
- **ArdiQ siempre con msgpack (su codec por defecto), nunca con pickle**, por el riesgo de ejecución de código en el worker.
- **Secretos:**
  - Solo en `.env`, que nunca se sube; `.env.example` lleva valores falsos.
  - `SecretStr` en `Settings`, y `hide_input_in_errors=True` en todas las clases de configuración: sin esto, Pydantic muestra el valor (por ejemplo, una API key demasiado corta) en el mensaje de error.
  - Los valores de ejemplo que deban ser secretos son inválidos a propósito (`API_KEY=change-me` es demasiado corta), para que nada arranque con una clave pública.
  - Docker Compose exige los secretos (`${VAR:?}`) en lugar de usar valores por defecto débiles.
  - Escaneo de secretos con push protection en GitHub (ver "Estado actual").
- **Dependencias** fijadas con `uv.lock`, con Dependabot activo.
- **Docker:** imágenes ligeras y sin ejecutar como root.
- **SSRF** (PulseOps visita URLs que da el usuario), en `pulseops/security/ssrf.py` (ADR-023):
  - Solo `http` y `https`, sin credenciales en la URL; se acepta cualquier puerto.
  - Si el host es un nombre, se resuelve el DNS de forma async con timeout. Se bloquea si **alguna** IP resultante no está permitida. Si el DNS falla, se acepta: el check lo marcará como `dns_error` y se volverá a validar.
  - Regla de IP permitida:
    1. Desenvolver las IPv4 escondidas en IPv6: `::ffff:` (mapped), 6to4, Teredo y NAT64 `64:ff9b::/96`. La IPv4 de dentro se valida **también**.
    2. Permitida solo si `is_global`, no multicast, no `::/96` (IPv4-compatible) y no `64:ff9b:1::/48`. No basta con `is_global`.
  - El error es genérico: nunca revela la IP ni a qué resuelve un nombre.
  - `ALLOW_PRIVATE_TARGETS=true` desactiva el bloqueo en instalaciones dentro de una red propia.
  - Validar al crear y editar (Fase 2), en **cada check** (por el DNS rebinding) y en **cada redirección**, con un máximo de 5 (Fase 3).
  - Verificación SSL siempre activa.
  - El repositorio solo acepta `ValidatedUrl`, que únicamente crea el paso de validación. Así es imposible guardar por accidente una URL sin validar.
- **Errores de la API:**
  - Formato RFC 9457 + campo `code`.
  - Los 500 son siempre genéricos.
  - Nunca se devuelve `input`, SQL, nombres de restricciones o tablas, ni trazas.
- **API key:** obligatoria, de 32 caracteres o más, como `SecretStr` en `ApiSettings` (el worker nunca la ve). Se compara con `secrets.compare_digest` y nunca aparece en logs.
- **CORS:** desactivado. Si algún día hace falta, solo para dominios concretos, nunca `*`.
- **Exposición:** la API se publica solo en `127.0.0.1` hasta la Fase 9.
- **Futuro:**
  - Fase 8: escapar siempre la salida HTML (XSS).
  - Fase 10: filtrar por dueño en una única capa de acceso a datos y limitar el número de monitores por usuario.

---

## Arquitectura (flujo)

1. El usuario usa la **API (FastAPI)** para añadir monitores → se guardan en **PostgreSQL**.
2. Un **cron de ArdiQ** decide qué monitores tocan y deja encargos en **Valkey**.
3. El **worker de ArdiQ** coge cada encargo, comprueba la web con **httpx2** y guarda el resultado en **PostgreSQL**.
4. La API calcula estado, uptime y tiempos a partir del historial.
5. (Post-MVP) Si hay caída → alerta por **Telegram**; métricas en **Grafana**; todo detrás de **Nginx/Caddy** en un VPS.

---

## MVP (definido y aprobado)

**Incluye:**
1. CRUD de monitores: URL, nombre e intervalo.
2. Comprobaciones automáticas según el intervalo de cada monitor.
3. Historial de comprobaciones.
4. Estado actual, tiempo de respuesta medio y uptime por monitor.
5. Todo levantable con `docker compose up` (API, worker, PostgreSQL, Valkey).
6. Tests + CI en GitHub Actions.

**Reglas de negocio decididas:**
- **Una web está caída si:** no responde, devuelve 4xx/5xx o tarda **más de 10 s**.
- **Intervalo:** configurable por monitor, **mínimo 30 s**.
- **Retención del historial:** **30 días**; lo más antiguo se borra automáticamente.

**Fuera del MVP:** alertas, incidentes, interfaz visual, usuarios/login, despliegue.

---

## Roadmap

### MVP

**Fase 0 — Cimientos**
Proyecto creado con `uv init` y dependencias base instaladas (FastAPI, uvicorn, httpx, ArdiQ, SQLAlchemy, Alembic; Ruff y pytest como dependencias de desarrollo). App FastAPI mínima con un endpoint `/health`. `docs/decisions.md` (con las decisiones ya tomadas), estructura de carpetas, Dockerfile y Docker Compose con API, PostgreSQL y Valkey, prueba de `ardiq doctor`. Primer commit y push a GitHub.
- A decidir: versión de Python, estructura de carpetas, Valkey o Redis (según `ardiq doctor`).
- Terminada cuando: `docker compose up` levanta todo sin errores, `/health` responde, Swagger se abre en `/docs` y el broker queda decidido.

**Fase 1 — Modelo de datos**
Tablas de monitores y comprobaciones con SQLAlchemy; primera migración con Alembic.
- Decidido (ADR-009 a ADR-016):
  - asyncpg.
  - `monitors`: `id` entero interno + `public_id` UUID v7.
  - `checks`: PK compuesta `(monitor_id, scheduled_at)` y `error_kind` con valores cerrados.
  - CHECK en la BD como defensa en profundidad y cascada `ON DELETE` hecha por PostgreSQL.
  - BRIN en `scheduled_at`.
  - pydantic-settings, servicio `migrate` con 3 roles y tests sobre una BD separada (`pulseops_test`).
- Terminada cuando:
  - `docker compose down -v && docker compose up --build` migra solo y la API queda healthy;
  - downgrade y upgrade funcionan, y `alembic check` está limpio;
  - Ruff (con S) y pytest en verde, incluidos los tests de permisos;
  - Toni lo prueba.

**Fase 2 — API de monitores**
CRUD con FastAPI, validaciones (URL válida, intervalo ≥ 30 s), Swagger.
- Decidido (ADR-017 a ADR-030):
  - rutas `/api/v1/monitors`, edición solo con PATCH y el campo `id` = `public_id`;
  - errores RFC 9457 + `code`;
  - paginación limit/offset;
  - normalización de URLs, SSRF y `ValidatedUrl`;
  - API key en `ApiSettings`, router → repositorio, `DOCS_ENABLED`, sin CORS y API solo en `127.0.0.1`.
- Terminada cuando:
  - CRUD completo desde Swagger con "Authorize";
  - las URLs duplicadas "disfrazadas" dan 409, y las internas o con credenciales, 422;
  - los errores siguen RFC 9457;
  - tests en verde;
  - Toni lo prueba.

**Fase 3 — El comprobador**
Función que visita una URL con httpx2 y devuelve estado, código HTTP y latencia según el criterio de caída.
- Ya decidido:
  - validación SSRF en cada check y en cada redirección (máximo 5);
  - GET sin descargar el cuerpo de la respuesta;
  - verificación SSL siempre activa;
  - el motivo del fallo usa los `error_kind` de la BD (timeout, dns_error, connection_error, ssl_error, http_error, blocked_target).
- A decidir:
  - seguir redirecciones o no, User-Agent y detalles de timeouts;
  - **resolución DNS**: `loop.getaddrinfo` usa hilos y su timeout no libera el hilo, lo que en cada check importa más que en la API. Comparar con un resolvedor async (por ejemplo, `aiodns`).
- Terminada cuando: tests cubren web OK, web con error y web lenta.

**Fase 4 — Checks automáticos (ArdiQ)**
Lanzar los checks según el intervalo de cada monitor y guardar resultados.
- Ya decidido: los checks se insertan con `ON CONFLICT DO NOTHING` sobre la PK `(monitor_id, scheduled_at)`, que los hace idempotentes frente a las reejecuciones de ArdiQ. `scheduled_at` es la hora en que tocaba el check, no la real.
- A decidir (**decisión clave del MVP, investigar a fondo**): un cron global que cada pocos segundos mira qué monitores tocan vs. una tarea programada por monitor.
- Terminada cuando: al añadir una web aparecen comprobaciones solas.

**Fase 5 — Estado y estadísticas**
Endpoints de estado actual, uptime y latencia media; limpieza automática de datos de más de 30 días.
- Ya decidido: el historial de checks se pagina **por cursor** sobre `(monitor_id, scheduled_at)`, no con offset.
- A decidir: cálculo del uptime (por número de checks o por tiempo).
- Terminada cuando: se puede consultar cómo ha ido una web en la última semana.

**Fase 6 — CI y presentación**
GitHub Actions (Ruff + tests con PostgreSQL y Valkey como servicios + `alembic check`), README con diagrama, instrucciones y capturas.
- Terminada cuando: check verde en GitHub y release **v0.1.0**. → **MVP completo.**

### Post-MVP
- **Fase 7 — Alertas e incidentes:** Telegram, agrupar caídas en incidentes, anti-spam (p. ej. avisar tras N fallos seguidos).
- **Fase 8 — Interfaz y métricas:** Grafana y/o HTMX; métricas Prometheus.
- **Fase 9 — Despliegue:** VPS, Nginx o Caddy, dominio, HTTPS, despliegue automático.
  - En el proxy: límite de tamaño de las peticiones y de intentos fallidos de API key.
  - Poner la API detrás del proxy y quitar su publicación en `127.0.0.1`.
  - Decidir `DOCS_ENABLED` en producción.
  - El SSRF ya contempla un VPS solo IPv6 con DNS64/NAT64.
- **Fase 10 — Extras:** usuarios y login, página de estado pública, etc.
  - Sustituir la API key por usuarios.
  - Filtro por dueño en el repositorio, que es la única capa de acceso a datos.
  - La restricción `uq_monitors_url` pasa a ser única por `(owner_id, url)`.

---

## Convenciones

- **Ramas:** una por fase, en inglés (`phase-0-foundations`, `phase-1-data-model`…), fusionadas a `main` por PR.
- **Commits:** Conventional Commits en inglés (`feat:`, `fix:`, `chore:`, `docs:`, `test:`), pequeños y descriptivos.
- **Idioma del proyecto: inglés.** Todo lo que vive en el repo va en inglés: código (nombres, comentarios, docstrings), README, `docs/decisions.md` y cualquier otra documentación, mensajes de commit, ramas, issues y Pull Requests.
- **Idioma de la conversación: español.** Las explicaciones, preguntas y resúmenes para Toni se dan en español.
- **Calidad:** todo el código pasa Ruff y pytest antes de cada PR. Tests para cada pieza con lógica.
- **Configuración:** variables de entorno (`.env`, con `.env.example` en el repo). Nunca subir secretos.
- **Decisiones:** cada una en `docs/decisions.md`.

---

## Estado actual

- **Fase actual:** Fase 2 — API de monitores, **construida y verificada** en la rama `phase-2-monitors-api`. Falta que Toni la pruebe y abrir el PR.
- **Hecho en Fase 2:**
  - CRUD en `/api/v1/monitors` con API key;
  - errores RFC 9457 + `code`;
  - `security/` (normalización, SSRF y `ValidatedUrl`);
  - `repositories/monitors.py`;
  - `ApiSettings` y `DOCS_ENABLED`;
  - API solo en `127.0.0.1:8000`;
  - 143 tests.
- **Cambios descubiertos en Fase 2:**
  - `HttpUrl` de Pydantic rechaza por su cuenta las URLs de más de 2083 caracteres. El esquema usa ese mismo límite de entrada, para dar un error claro. El límite de 2048 tras normalizar se mantiene.
  - FastAPI 0.162 guarda los routers incluidos como un bloque anidado (`_IncludedRouter`), no como rutas sueltas en `app.routes`.
  - `Monitor` usa `eager_defaults`, que recoge `public_id` y las fechas con `RETURNING`. Sin esto, leer `updated_at` tras un UPDATE en async falla.
  - El SSRF también bloquea los nombres internos de Docker (por ejemplo, `http://postgres:5432/` se resuelve a una IP privada). Lo he comprobado contra el stack real.
- **Hecho en Fase 1:**
  - `config.py` con pydantic-settings;
  - modelos `Monitor` y `Check` en `pulseops/db/`;
  - migración `0001`, revisada a mano;
  - servicio `migrate` con 3 roles creados por `docker/postgres/initdb/01-roles.sh`;
  - Valkey con contraseña y secretos obligatorios en Compose;
  - Ruff con reglas "S" y Dependabot;
  - 29 tests sobre `pulseops_test` (restricciones, permisos, migraciones y `alembic check`).
- **Cambios descubiertos en Fase 1:**
  - SQLAlchemy 2.1 necesita el extra `sqlalchemy[asyncio]`, porque ya no instala `greenlet` por defecto.
  - El healthcheck de PostgreSQL va por TCP: durante la primera inicialización solo escucha por socket y `migrate` podría arrancar antes de que existieran los roles.
  - Los tests async usan el plugin de pytest de anyio (ya viene con FastAPI), sin pytest-asyncio.
  - Los roles solo se crean al iniciar un volumen vacío: si cambian sus contraseñas en `.env`, hay que recrear el volumen con `docker compose down -v`, que borra los datos.
- **Hecho en Fase 0:**
  - proyecto uv con Python 3.13 y estructura `src/pulseops/`;
  - app FastAPI con `/health` y Swagger;
  - módulo `pulseops/queue/` con ArdiQ aislado;
  - Dockerfile + Docker Compose (API, PostgreSQL 18, Valkey 9) con healthchecks;
  - `ardiq doctor` OK contra Valkey;
  - cambio de httpx a httpx2;
  - ADR-001 a ADR-008.
- **Pendiente de decidir:** interfaz visual (post-MVP), Nginx o Caddy (Fase 9).
- **Pendiente de hacer (Toni):** activar el escaneo de secretos con push protection en GitHub. El repo es privado y ahí GitHub no lo ofrece gratis (requiere Secret Protection, de pago): revisar los ajustes del repo o activarlo cuando el repo pase a público.
- **Notas para más adelante:**
  - En el VPS (Fase 9), activar `vm.overcommit_memory = 1` en el host, que Valkey lo pide en sus logs.
  - Si la tabla `checks` crece mucho, particionarla por fecha o pasar a TimescaleDB. La PK `(monitor_id, scheduled_at)` ya está preparada para ello.
- **Siguiente paso:** Toni prueba la Fase 2 → PR hacia `main`. Después, la Fase 3 (el comprobador) en modo plan (regla 8).
