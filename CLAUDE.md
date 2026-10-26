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
7. Mantén este archivo al día: actualiza "Estado actual" al cerrar cada fase.

### El ciclo de cada fase
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
| Cliente HTTP | httpx2 (async) | Hace las comprobaciones y mide el tiempo de respuesta (sustituye a httpx, ver ADR-008) |
| Cola de tareas | ArdiQ | Programa y ejecuta los checks en segundo plano (workers) |
| Broker | Valkey | Memoria rápida donde ArdiQ guarda la cola (confirmado con `ardiq doctor`, ver ADR-007) |
| Base de datos | PostgreSQL | Monitores, historial de checks, incidentes |
| ORM y migraciones | SQLAlchemy 2 (async) + Alembic | Acceso a la BD y cambios de esquema |
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
- A decidir: campos de un monitor y qué se guarda de cada check.
- Terminada cuando: las tablas se crean con una migración.

**Fase 2 — API de monitores**
CRUD con FastAPI, validaciones (URL válida, intervalo ≥ 30 s), Swagger.
- A decidir: rutas de la API y formato de errores.
- Terminada cuando: Toni gestiona monitores desde Swagger.

**Fase 3 — El comprobador**
Función que visita una URL con httpx2 y devuelve estado, código HTTP y latencia según el criterio de caída.
- A decidir: seguir redirecciones o no, User-Agent, detalles de timeouts.
- Terminada cuando: tests cubren web OK, web con error y web lenta.

**Fase 4 — Checks automáticos (ArdiQ)**
Lanzar los checks según el intervalo de cada monitor y guardar resultados.
- A decidir (**decisión clave del MVP, investigar a fondo**): un cron global que cada pocos segundos mira qué monitores tocan vs. una tarea programada por monitor.
- Terminada cuando: al añadir una web aparecen comprobaciones solas.

**Fase 5 — Estado y estadísticas**
Endpoints de estado actual, uptime y latencia media; limpieza automática de datos de más de 30 días.
- A decidir: cálculo del uptime (por número de checks o por tiempo).
- Terminada cuando: se puede consultar cómo ha ido una web en la última semana.

**Fase 6 — CI y presentación**
GitHub Actions (Ruff + tests con PostgreSQL y Valkey como servicios), README con diagrama, instrucciones y capturas.
- Terminada cuando: check verde en GitHub y release **v0.1.0**. → **MVP completo.**

### Post-MVP
- **Fase 7 — Alertas e incidentes:** Telegram, agrupar caídas en incidentes, anti-spam (p. ej. avisar tras N fallos seguidos).
- **Fase 8 — Interfaz y métricas:** Grafana y/o HTMX; métricas Prometheus.
- **Fase 9 — Despliegue:** VPS, Nginx o Caddy, dominio, HTTPS, despliegue automático.
- **Fase 10 — Extras:** usuarios y login, página de estado pública, etc.

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

- **Fase actual:** Fase 0 — Cimientos (terminada, pendiente de fusionar el PR) → siguiente: Fase 1 — Modelo de datos.
- **Hecho en Fase 0:** proyecto uv con Python 3.13 y estructura `src/pulseops/`; app FastAPI con `/health` y Swagger; módulo `pulseops/queue/` con ArdiQ aislado; Dockerfile + Docker Compose (API, PostgreSQL 18, Valkey 9) con healthchecks; `ardiq doctor` OK contra Valkey; cambio de httpx a httpx2; ADR-001 a ADR-008 en `docs/decisions.md`.
- **Pendiente de decidir:** interfaz visual (post-MVP), Nginx o Caddy (Fase 9).
- **Notas para más adelante:** en el VPS (Fase 9), activar `vm.overcommit_memory = 1` en el host, que Valkey lo pide en sus logs.
- **Siguiente paso:** fusionar el PR de la Fase 0 y empezar la Fase 1 investigando los campos de un monitor y qué se guarda de cada check.
