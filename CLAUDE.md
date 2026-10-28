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
14. **Mantén `docs/evidence.md` (registro de datos verificados) al día.**
    - Solo datos oficiales que salgan de un comando, un test o una prueba realmente hecha, con fecha y forma de reproducirlos. Nunca estimaciones ni datos de memoria.
    - Al cerrar cada fase: añadir su fila a la tabla por fases (tests, Ruff, ADRs, verificación manual) y actualizar el desglose de tests, las garantías, las versiones y el tamaño.
    - Cada hallazgo sobre una librería o comportamiento verificado va también a su tabla.
    - **Sin datos personales ni de la red de Toni:** nada de IPs locales, rutas de su ordenador, nombre de usuario, email o sistema operativo de su equipo. En su lugar se usan marcadores como `<local IP>`.
    - Tiene que poder leerse **tal cual cuando el repo sea público**.
15. **Nada sale de git sin el OK de Toni.**
    - **Antes de cada commit**, enséñale:
      - qué archivos cambian;
      - un resumen de los cambios;
      - el mensaje de commit propuesto.

      Después, espera su OK.
    - **Explica cada cosa técnica del commit** (lo que se añade, se cambia o se crea):
      - **Tono:** informal, nada profesional, como si se lo contaras a alguien que está aprendiendo, con ejemplos de andar por casa si ayudan.
      - **Términos técnicos:** cada uno se explica en la misma frase.
      - **Extensión:** pocas líneas por cosa; solo se profundiza si Toni lo pide.
      - **Formato por cada cambio:**
        - **Qué es:** una frase sencilla.
        - **Para qué sirve:** el problema que resuelve.
        - **Por qué así:** por qué esta forma y no otra (si aplica).
      - **Ejemplo:** "`trust_env=False`: le dice al programa que ignore los proxies configurados en el sistema. Sirve para que nadie pueda desviar nuestras visitas por otro sitio y saltarse el control de seguridad. Por qué así: si hiciera caso al proxy, comprobaríamos la dirección del proxy en vez de la de la web."
      - **Si el commit solo tiene documentación o formato**, basta con una línea que lo diga.
    - **Lo mismo antes de cada push y de abrir cada PR:** enséñale qué se sube, o el título y la descripción del PR, y espera su OK.
    - **Sin líneas de atribución:** ni los commits ni los PR llevan "Co-Authored-By: Claude", "Generated with Claude Code" ni ninguna otra. Está desactivado también en `~/.claude/settings.json` (`attribution`).

16. **Construye poco a poco y explica cada paso sobre la marcha.** Al salir del modo plan, no lo construyas todo para explicarlo al final, porque eso satura.
    - Avanza en pasos pequeños: añade una pieza y explícala en ese momento ("he añadido esto, hace tal y tal") con el tono de la regla 15. Después sigue con la siguiente.
    - Cada explicación debe ser corta, para que Toni pueda seguir el hilo y preguntar antes de que se acumulen cosas.

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
- **Comprobado contra Valkey real** (Fase 4, `tests/test_queue_broker.py`):
  - un `task_id` repetido se ignora **solo mientras la tarea existe**; después de terminar, se ejecuta otra vez;
  - `expire_ms` descarta de verdad las tareas que no empiezan a tiempo;
  - `ardiq.testing.inline` ignora los retrasos y `expire_ms`;
  - no hay opción de timeout de conexión: un broker inalcanzable tarda unos 16 s en fallar.
- **Hallazgos para el autor**, abiertos por Toni como issues [#9](https://github.com/17tayyy/ardiq/issues/9), [#10](https://github.com/17tayyy/ardiq/issues/10) (los ejemplos de ArdiQ publican Redis en `0.0.0.0` sin contraseña) y [#11](https://github.com/17tayyy/ardiq/issues/11); apuntados en `docs/evidence.md`, "Upstream issues":
  - la guía de `task_id` no aclara que el deduplicado acaba al terminar la tarea;
  - en modo `burst`, un segundo `app.run()` sobre la misma instancia no procesa la cola. Reproducido con Redis 7.4.12 y Valkey 9.1.2.

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
- **Valkey** con contraseña. Los puertos de PostgreSQL y Valkey no se publican fuera de Docker; si hace falta en local, solo en `127.0.0.1`. Para los tests: PostgreSQL en `127.0.0.1:5432` y Valkey en `127.0.0.1:6380` (ADR-043).
- **La API nunca recibe la contraseña de Valkey:** `broker_url` vive en `BrokerSettings`, que solo usa el worker (ADR-043).
- **Las URLs de los monitores nunca van a los logs**, porque pueden llevar tokens (ADR-044):
  - el worker registra solo `public_id`, arriba/caído, `error_kind` y ms, nunca la URL ni el `error_detail`;
  - las tareas de la cola solo llevan ids;
  - los loggers de `httpx2` y `httpcore2` están en WARNING (httpx2 registra cada URL a nivel INFO);
  - el motor de la BD usa `hide_parameters=True`, para que los errores no lleven los parámetros de la consulta.
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
  - En el comprobador, la validación se hace **al abrir cada conexión TCP**, con la IP fijada (ADR-031): se resuelve, se validan todas las IPs y se conecta a una de esas mismas. El cliente HTTP usa `trust_env=False` (ignora `HTTP(S)_PROXY`) y no reutiliza conexiones.
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
- Decidido (ADR-031 a ADR-038):
  - SSRF al abrir cada conexión, con la IP fijada, y `trust_env=False`;
  - seguir hasta 5 redirecciones (más, un bucle o un esquema raro → `http_error`);
  - un plazo total de 10 s, y `response_time_ms` hasta las cabeceras finales;
  - GET sin descargar el cuerpo;
  - User-Agent `PulseOps/<versión> (uptime monitor)`;
  - conexiones nuevas en cada check;
  - DNS con `getaddrinfo` en un pool de hilos propio;
  - `Checker` / `CheckOutcome` en `pulseops/checker/`, con el comando `python -m pulseops.checker <url>`;
  - cobertura con `pytest-cov` y smoke test en `scripts/smoke_test.py`.
- Terminada cuando:
  - hay tests de OK, 404/500, timeout, redirecciones, conexión rechazada, certificados inválidos, DNS y rebinding;
  - el comando funciona dentro del contenedor;
  - Toni lo prueba.

**Fase 4 — Checks automáticos (ArdiQ)**
Lanzar los checks según el intervalo de cada monitor y guardar resultados.
- Ya decidido: los checks se insertan con `ON CONFLICT DO NOTHING` sobre la PK `(monitor_id, scheduled_at)`, que los hace idempotentes frente a las reejecuciones de ArdiQ. `scheduled_at` es la hora en que tocaba el check, no la real.
- Decidido (ADR-039 a ADR-045):
  - **Planificador global:** un `@app.cron(every=5, coalesce=True)` reclama los monitores con `next_check_at <= now()` (columna nueva en `monitors`, migración `0002`) con `FOR NO KEY UPDATE SKIP LOCKED`, como máximo 500 por turno. Encola `check_monitor(monitor_id, scheduled_at_us)` con id fijo `check:<id>:<µs>` **antes** del commit: si encolar falla, rollback y el siguiente turno lo reintenta. La agenda vive en PostgreSQL, no en Valkey.
  - **Siguiente turno:** `anterior + k × intervalo`; los periodos perdidos se saltan sin perder el ritmo de cada monitor.
  - **Al crear, al cambiar la URL o el intervalo, o al reactivar:** `next_check_at = now()`. Planificar no cambia `updated_at`.
  - **La tarea:**
    - lee el monitor con una sesión, la cierra, hace el check y guarda con otra sesión: nunca tiene una conexión de BD abierta durante el check;
    - si el monitor está borrado o desactivado, no hace nada.
  - **Worker:** `concurrency=32`; carriles `checks` y `scheduler`, con `limits={"checks": 31}` para reservar un hueco al planificador. Cada tarea tiene `expire_ms` = su intervalo, `max_retries=3` (solo fallos de infraestructura) y `timeout=30`.
  - **Logs:** la URL y el `error_detail` nunca van a los logs (pueden llevar tokens); solo `public_id`, arriba/caído, `error_kind` y ms. La tarea no lleva la URL, así que tampoco aparece en Valkey.
  - **`BrokerSettings` aparte:** la API no recibe la contraseña de Valkey.
  - **Tests:** Valkey se publica en `127.0.0.1` y los tests de ArdiQ usan una cola propia.
  - **Verificación con `psql` como `pulseops_app`**, nunca como `postgres`.
  - **Latido del planificador:** tabla `scheduler_heartbeat` (migración `0003`), con `last_success_at` en la misma transacción de cada turno, incluidos los vacíos.
  - **`restart: unless-stopped`** en `api`, `worker`, `postgres` y `valkey`; en `migrate`, no.
- Terminada cuando: al añadir una web aparecen comprobaciones solas.

**Fase 5 — Estado y estadísticas**
Endpoints de estado actual, uptime y latencia media; limpieza automática de datos de más de 30 días.
- Ya decidido: el historial de checks se pagina **por cursor** sobre `(monitor_id, scheduled_at)`, no con offset.
- Ya decidido: los huecos sin checks (por ejemplo, con el worker parado) cuentan como **"sin datos"**, ni arriba ni caída.
- Pendiente de la Fase 4: ampliar `scripts/smoke_test.py` para que compruebe que un monitor nuevo recibe checks. Se hará por la API cuando exista el endpoint de historial; hasta entonces se mira con `psql`.
- A decidir: cálculo del uptime (por número de checks o por tiempo).
- Terminada cuando: se puede consultar cómo ha ido una web en la última semana.

**Fase 6 — CI y presentación**
GitHub Actions (Ruff + tests con PostgreSQL y Valkey como servicios + `alembic check`), README con diagrama, instrucciones y capturas.
- Terminada cuando: check verde en GitHub y release **v0.1.0**. → **MVP completo.**

### Post-MVP
- **Pendiente sin fase asignada:** **códigos de respuesta esperados configurables por monitor.** Hoy, un 401/403 de una API protegida, o de una web que bloquea robots, sale como caída.
- **Fase 7 — Alertas e incidentes:** Telegram, agrupar caídas en incidentes, anti-spam (p. ej. avisar tras N fallos seguidos).
  - "Quién vigila al vigilante": que `/health` indique si el planificador ha funcionado hace poco, para poder alertar si se para. El dato ya existe desde la Fase 4: `scheduler_heartbeat.last_success_at` (ADR-045).
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
- **Commits:** Conventional Commits en inglés (`feat:`, `fix:`, `chore:`, `docs:`, `test:`), pequeños y descriptivos, sin líneas de atribución y siempre con el OK previo de Toni (regla 15).
- **Idioma del proyecto: inglés.** Todo lo que vive en el repo va en inglés: código (nombres, comentarios, docstrings), README, `docs/decisions.md` y cualquier otra documentación, mensajes de commit, ramas, issues y Pull Requests.
- **Idioma de la conversación: español.** Las explicaciones, preguntas y resúmenes para Toni se dan en español.
- **Calidad:** todo el código pasa Ruff y pytest antes de cada PR. Tests para cada pieza con lógica.
- **Configuración:** variables de entorno (`.env`, con `.env.example` en el repo). Nunca subir secretos.
- **Decisiones:** cada una en `docs/decisions.md`.
- **Datos verificados** (tests, comprobaciones manuales, versiones, hallazgos): en `docs/evidence.md`.

---

## Estado actual

- **Fase actual:** Fase 5 — Estado y estadísticas, **no empezada**: falta el modo plan. Rama `phase-5-status-and-stats` creada desde `main`. Fase 4 cerrada (PR #5 fusionado el 2026-10-27, verificada por Toni).
- **Hecho en Fase 4:**
  - el worker (`ardiq run pulseops.worker:app`) con un planificador cada 5 s y la tarea `check_monitor`;
  - migraciones `0002` (`next_check_at`) y `0003` (`scheduler_heartbeat`);
  - repositorios de planificación y de checks;
  - reprogramación al editar;
  - `BrokerSettings`;
  - servicio `worker` en Compose y `restart: unless-stopped`;
  - Valkey en `127.0.0.1:6380` para los tests;
  - 213 tests (cobertura del 97 %), 4 de ellos contra Valkey real;
  - ADR-039 a ADR-045.
- **Cambios descubiertos en Fase 4:**
  - **httpx2 registra cada URL visitada a nivel INFO** (`HTTP Request: GET <url>`), y httpcore2 da aún más detalle a nivel DEBUG. Como `ardiq run` muestra INFO, los tokens de las URLs habrían acabado en los logs. El comprobador sube esos dos loggers a WARNING. Hay un test que lo demuestra.
  - **SQLAlchemy mete los parámetros de la consulta en sus mensajes de error**, y estos podrían incluir el `error_detail` con la URL. ArdiQ guarda el error de cada tarea fallida en su log y en la cola de fallidas. Por eso el motor usa `hide_parameters=True`. El `BrokerError` de ArdiQ no muestra la contraseña de Valkey.
  - **`UPDATE … RETURNING` no conserva el orden del `CTE`.** Un test fallaba de forma aleatoria; ahora se ordena en Python.
  - **La reclamación usa `FOR NO KEY UPDATE`, no `FOR UPDATE`.** Con el candado fuerte, guardar un check de un monitor reclamado esperaba al commit del planificador, porque la clave foránea pide un candado compartido. Hay un test que lo demuestra.
  - **`scheduled_at` viaja en microsegundos, no en milisegundos.** PostgreSQL guarda microsegundos, y con milisegundos el check no caería exactamente en el turno reclamado.
  - **Añadir `next_check_at` con `DEFAULT now()` no reescribe la tabla:** `now()` no es volátil, así que PostgreSQL lo guarda como valor por defecto (`atthasmissing`). Comprobado en PostgreSQL 18.
  - **En la máquina de desarrollo, el puerto 6379 lo ocupa otro Redis** (el del repo de ArdiQ). Por eso Valkey se publica en el 6380.
  - **El test del log sin contraseña tarda unos 10 s,** porque ArdiQ reintenta la conexión y no tiene opción para acortarlo. La suite pasa de ~7 s a ~17 s.
  - **`example.com` sigue sin responder desde la red de desarrollo** (repetido el 2026-10-27 a las 23:33 UTC, ya de madrugada en España y fuera de horario de partidos). La hipótesis "solo durante los partidos" no se confirma; la causa sigue estando en la red. Para verificar se sigue usando Google.
- **Hecho en Fase 3:**
  - `pulseops/checker/` (`Checker`, `CheckOutcome`, backend de red con IP fijada, comando `python -m pulseops.checker`);
  - DNS en un pool de hilos propio;
  - 26 tests del comprobador contra servidores HTTP y HTTPS locales reales (con `trustme`);
  - cobertura con `pytest-cov` (95 %);
  - `scripts/smoke_test.py` (22/22 contra el stack);
  - ADR-031 a ADR-038.
- **Cambios descubiertos en Fase 3:**
  - Desde la red de desarrollo, `example.com` (sus IPs de Cloudflare) no responde: la conexión se corta, también con `curl`. Otras webs, incluso detrás de Cloudflare, funcionan. Para verificar, se usa `https://www.google.com`.
    - Repetido el 2026-10-28: sigue igual (ver "Cambios descubiertos en Fase 4").
  - httpbin.org y httpbingo.org ya no redirigen a destinos arbitrarios (403 con una lista blanca), así que no sirven para probar "redirección a una IP interna". Para eso están los tests automáticos y los nombres DNS públicos tipo `169.254.169.254.nip.io`.
  - La cobertura necesita `concurrency = ["greenlet", "thread"]`: SQLAlchemy async ejecuta código en greenlets, y sin esto marca como no ejecutadas líneas que sí lo están.
  - httpcore2 hace el handshake TLS con el nombre del origen (`server_hostname`), no con la IP conectada; por eso fijar la IP no rompe HTTPS.
  - El servidor de pruebas debe usar `Server.close_clients()` (Python 3.13) al apagarse; sin ello, los tests tardaban 35 s en lugar de 0,6 s.
  - Identidad de git: `3fxsty` con el email noreply de GitHub. Los commits ya subidos conservan la identidad antigua.
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
  - `restart: unless-stopped` solo sirve tras reiniciar el equipo si el demonio de Docker arranca solo. En el VPS (Fase 9), comprobarlo (`systemctl is-enabled docker`).
  - Si la tabla `checks` crece mucho, particionarla por fecha o pasar a TimescaleDB. La PK `(monitor_id, scheduled_at)` ya está preparada para ello.
- **Siguiente paso:** la Fase 5 en modo plan (regla 8). Los cambios de cierre de la Fase 4 en este archivo y en `docs/evidence.md` van en el primer commit de la rama, con el OK de Toni.
