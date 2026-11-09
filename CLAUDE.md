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
| Lenguaje | Python 3.13 | Todo el backend (ADR-004) |
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
| CI/CD | GitHub Actions | Lint, tests y el stack entero con smoke test en cada PR y en cada push a `main` (ADR-053); CodeQL (default setup) analiza Python y Actions |
| Contenedores | Docker + Docker Compose | Levantar todos los servicios juntos |
| Interfaz | Swagger (MVP) → **pendiente**: Grafana y/o HTMX | Ver el estado |
| Alertas | Bot de Telegram (Bot API directa con httpx2, Fase 7, ADR-064) | Avisar al empezar y al acabar cada incidente |
| Proxy inverso | **pendiente**: Nginx o Caddy | Entrada desde internet + HTTPS |
| Servidor | VPS (Hetzner) | Producción |

### Notas sobre ArdiQ
- Cola de tareas con núcleo en Rust, async, sobre Redis Streams + Lua. Versión en uso: **1.2.1** (desde el PR #14, 2026-11-03). Docs: https://ardiq.bytay.dev · Repo: https://github.com/17tayyy/ardiq
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
- **Hallazgos para el autor**, abiertos por Toni como issues [#9](https://github.com/17tayyy/ardiq/issues/9), [#10](https://github.com/17tayyy/ardiq/issues/10) y [#11](https://github.com/17tayyy/ardiq/issues/11). **Los tres están arreglados en ArdiQ 1.2.1** (cerrados el 2026-10-28; las notas de la versión citan a Toni). Comprobado el 2026-11-03 contra Valkey real, con 1.2.0 y 1.2.1 lado a lado (`docs/evidence.md`, "Upstream issues"):
  - #9: la guía ya aclara que el deduplicado de `task_id` dura mientras la tarea existe (eso **no cambia**: sigue haciendo falta `ON CONFLICT DO NOTHING`). Además, al reencolar un id terminado se borra su resultado viejo. A PulseOps no le afecta: no lee resultados de tareas.
  - #10: los ejemplos publican Redis en `127.0.0.1`.
  - #11: un segundo `app.run()` en modo `burst` sobre la misma instancia ya procesa la cola.

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
  - PostgreSQL arranca con `log_error_verbosity=terse` (en el Compose). Sin esto, al repetir una URL (el 409) escribe en su propio log `DETAIL: Key (url)=(<la URL>) already exists`, y en una CHECK, la fila entera.
- **ArdiQ siempre con msgpack (su codec por defecto), nunca con pickle**, por el riesgo de ejecución de código en el worker.
- **Secretos:**
  - Solo en `.env`, que nunca se sube; `.env.example` lleva valores falsos.
  - `SecretStr` en `Settings`, y `hide_input_in_errors=True` en todas las clases de configuración: sin esto, Pydantic muestra el valor (por ejemplo, una API key demasiado corta) en el mensaje de error.
  - Los valores de ejemplo que deban ser secretos son inválidos a propósito (`API_KEY=change-me` es demasiado corta), para que nada arranque con una clave pública.
  - Docker Compose exige los secretos (`${VAR:?}`) en lugar de usar valores por defecto débiles.
  - Escaneo de secretos con push protection en GitHub, activo desde el 2026-10-28.
- **Avisos de vulnerabilidades:** `SECURITY.md` pide usar *Report a vulnerability* (Private vulnerability reporting, activo desde el 2026-10-29), nunca una issue pública. Objetivo de respuesta: acuse en 7 días.
- **CodeQL** (default setup, Python y Actions), activo desde el 2026-10-29. **No es un check obligatorio** del ruleset (decisión de Toni, 2026-10-29).
- **Dependencias** fijadas con `uv.lock`, con Dependabot activo: actualizaciones semanales, alertas de vulnerabilidades y PR de seguridad automáticos.
- **Docker:** imágenes ligeras y sin ejecutar como root.
- **Documentación de la API (`/docs`, `/redoc`, `/openapi.json`):** apagada por defecto (`DOCS_ENABLED=false`); solo se enciende en desarrollo desde `.env`.
- **Cadena de suministro** (ADR-055):
  - las imágenes de Docker se fijan por digest (`imagen:versión@sha256:…`, el del índice multiplataforma), y las acciones de GitHub por SHA, con un comentario de la versión;
  - Dependabot mantiene al día las dependencias, las imágenes y las acciones; los saltos mayores de PostgreSQL se hacen a mano.
- **CI (GitHub Actions)** (ADR-053 a ADR-055):
  - el token del workflow, en solo lectura (`permissions: contents: read`);
  - disparadores `pull_request` y `push` a `main`. **Nunca `pull_request_target`:** ejecutaría el código de un PR ajeno con los permisos del repo;
  - `persist-credentials: false` en el checkout;
  - ningún secreto real: `scripts/ci_env.py` genera un `.env` nuevo en cada ejecución, con valores aleatorios ocultos (`::add-mask::`);
  - sin artefactos, y `.env` fuera de la imagen (`.dockerignore`);
  - **los logs de CI serán públicos:** lo que se imprime al fallar (`docker compose logs`) está revisado línea a línea y no lleva secretos ni URLs que no sean las del smoke test;
  - `actionlint` antes de cada cambio del workflow.
- **`main` protegida con un ruleset** (2026-10-28): solo se cambia por PR, con los tres checks de CI en verde (Lint, Tests, Full stack, y solo valen si los da GitHub Actions); sin borrados, sin `force push` y sin excepciones (lista de bypass vacía). 0 aprobaciones obligatorias, porque GitHub no deja aprobar un PR propio.
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
- **Cursores del historial** (ADR-050): son opacos y se decodifican de forma estricta. Un cursor manipulado da 422 `invalid_cursor` sin devolverlo, y el monitor sale siempre de la URL, nunca del cursor.
- **Errores de la API:**
  - Formato RFC 9457 + campo `code`.
  - Los 500 son siempre genéricos.
  - Nunca se devuelve `input`, SQL, nombres de restricciones o tablas, ni trazas.
- **Alertas por Telegram** (Fase 7, ADR-063 a ADR-066):
  - el token del bot es `SecretStr` en `AlertSettings`, que solo usa el worker; **la API nunca lo recibe**;
  - el token va en la URL de la Bot API, así que nunca se registra la URL, ni el mensaje de las excepciones de httpx2, ni la respuesta de Telegram: solo el tipo de error y el código HTTP;
  - la dirección de la Bot API es fija en el código (`https://api.telegram.org`); ninguna variable la cambia, y los tests usan un `MockTransport`;
  - los mensajes van en texto plano y **nunca llevan la URL del monitor ni el `error_detail`** (Telegram es un tercero que guarda los mensajes);
  - el bot solo envía, nunca recibe: nada escucha a Telegram.
- **`/health/scheduler`** (ADR-068): sin API key y sin devolver la hora del último turno; en la Fase 9 necesita el límite de peticiones del proxy.
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
3. El **worker de ArdiQ** coge cada encargo, comprueba la web con **httpx2** y guarda el resultado en **PostgreSQL**. En la misma transacción decide si se abre o se cierra un **incidente** y, si es así, apunta el aviso pendiente (*outbox*) (Fase 7).
4. Otro **cron del worker** entrega los avisos pendientes por **Telegram**, con reintentos (Fase 7).
5. La API calcula estado, uptime y tiempos a partir del historial, y muestra los incidentes.
6. (Post-MVP) Métricas en **Grafana**; todo detrás de **Nginx/Caddy** en un VPS.

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
- Decidido (ADR-046 a ADR-052):
  - **Uptime por número de checks:** `checks arriba / checks con datos × 100`, con 3 decimales y `null` si no hay datos. Si un día se quiere "por tiempo", habrá que guardar el intervalo en cada check; con la retención de 30 días, el historial se completa solo en un mes.
  - **Estado actual:** `up` / `down` según el último check; `paused` si está desactivado; `unknown` si no hay checks o el último tiene más de 2 × intervalo + 60 s.
  - **Rutas:** `GET /api/v1/monitors/{id}/checks?limit=&cursor=` y `GET /api/v1/monitors/{id}/stats?period=24h|7d|30d` (por defecto `7d`). El historial incluye el `error_detail`.
  - **Latencia:** media y p95, solo de los checks que salieron arriba.
  - **Cálculo al vuelo** sobre la PK, medido con 86 400 filas (objetivo: menos de 100 ms para `30d`).
  - **Cursor opaco:** `base64url` de `v1:<µs>`; si está manipulado, 422 `invalid_cursor`.
  - **Retención:**
    - un cron cada hora, en su propio carril `maintenance` (límite 1);
    - borra por lotes de 5 000, como máximo 60 s por pasada, y lo que quede se borra en la siguiente;
    - `checks` baja a un límite de 30, para que el planificador conserve siempre su hueco;
    - borra por `ctid` y vuelve a comprobar la fecha en el propio `DELETE`. Nunca recorre la tabla entera; PostgreSQL elige entre el BRIN y la PK.
  - **Smoke test:** se amplía con `/checks` y `/stats`, todo por la API (29 casos).
  - **Medición:** `scripts/measure_queries.py`.
- Terminada cuando: se puede consultar cómo ha ido una web en la última semana.

**Fase 6 — CI y presentación**
GitHub Actions (Ruff + tests con PostgreSQL y Valkey como servicios + `alembic check`), README con diagrama, instrucciones y capturas.
- Decidido (ADR-053 a ADR-058):
  - **PostgreSQL y Valkey en CI con el mismo `docker compose`** que en local, no con los services de GitHub: estos no pueden montar el script de roles ni arrancar Valkey con contraseña.
  - **Tres jobs en `.github/workflows/ci.yml`:**
    - `lint`: Ruff check + format;
    - `test`: pytest con cobertura, más `alembic upgrade head` + `alembic check` como paso propio;
    - `stack`: `docker compose up --build --wait` + `scripts/smoke_test.py`, con los logs del Compose si falla.
  - **Secretos de CI:** un `.env` nuevo en cada ejecución a partir de `.env.example`, con valores aleatorios ocultos en los logs (`::add-mask::`). Ninguna contraseña escrita en el repo.
  - **Seguridad del workflow** (ver "Seguridad"):
    - acciones fijadas por SHA, con un comentario de la versión;
    - `permissions: contents: read`;
    - disparadores `push` a `main` y `pull_request`, nunca `pull_request_target`;
    - `persist-credentials: false`, `concurrency`, `timeout-minutes` y runner `ubuntu-24.04` fijo.
  - **Imágenes de Docker fijadas por digest** (`imagen:versión@sha256:…`, el del índice multiplataforma): `postgres`, `valkey`, la base de Python y la de uv del Dockerfile. La etiqueta exacta hace de comentario de la versión, y Dependabot actualiza las dos cosas a la vez.
  - **Suelo de cobertura del 95 %** en `pyproject.toml`, igual en local que en CI.
  - **README de escaparate,** con el diagrama en Mermaid, el badge de CI y 2 capturas hechas por Toni, sin datos personales. **Sin cifras del proyecto escritas a mano** (ver "Convenciones").
  - **Licencia MIT** ("Copyright (c) 2026 3fxsty"), en `LICENSE` y en `pyproject.toml`.
  - **Release:** etiqueta anotada `v0.1.0` sobre `main` tras fusionar el PR, y release de GitHub con notas a mano. Sin `CHANGELOG.md` ni imagen en GHCR (hasta la Fase 9).
  - **El repo pasa a público al publicar la v0.1.0,** después de escanear todo el historial con `gitleaks`.
    - El historial se queda como está: a Toni no le importa que se vean su nombre y el email antiguo.
    - Al pasar a público, Toni activa el escaneo de secretos con push protection y la protección de `main`, que exige el check verde.
- Terminada cuando: check verde en GitHub y release **v0.1.0**. → **MVP completo.**

### Post-MVP
- **Pendiente sin fase asignada:**
  - **códigos de respuesta esperados configurables por monitor.** Hoy, un 401/403 de una API protegida, o de una web que bloquea robots, sale como caída. Con las alertas de la Fase 7 molesta más; mientras tanto, ese monitor se puede pausar;
  - **recordatorios** de un incidente que sigue abierto ("sigue caída tras 1 h");
  - **comandos del bot** (`/status`): exigiría que el bot reciba mensajes;
  - **otros canales** de aviso (email, Discord), sobre la interfaz `Notifier`.
- **Fase 7 — Alertas e incidentes:** Telegram, agrupar caídas en incidentes, anti-spam y vigilar el planificador.
  - Decidido (ADR-059 a ADR-070):
    - **Incidente:** se abre con **2 fallos seguidos** y se cierra con **2 aciertos seguidos** (constantes globales). `started_at` = el primer fallo de la racha y `resolved_at` = el primer acierto. Un hueco de más de 2 × intervalo + 60 s corta la racha (como ADR-047). Una racha nunca empieza antes del `resolved_at` del incidente anterior.
    - **Detección en la transacción del check** (`run_check`):
      1. `pg_advisory_xact_lock(<espacio de incidentes>, monitor_id)`: de uno en uno por monitor, sin bloquear al planificador;
      2. insertar el check;
      3. evaluar **solo si se insertó y es el más reciente** (un check tardío se guarda, pero no decide) y si el monitor sigue activo;
      4. abrir o cerrar el incidente y apuntar el aviso;
      5. un solo commit.
      La regla es una función pura en `pulseops/incidents.py`.
    - **Tabla `incidents`** (migración `0004`):
      - `id` + `public_id` UUID v7, `monitor_id` (cascada), `started_at`, `resolved_at`, `error_kind`, `status_code` y `resolution` (`recovered` / `paused` / `monitor_changed`);
      - un solo incidente abierto por monitor (índice único parcial) y único `(monitor_id, started_at)`.
      - **Pausar o cambiar la URL** cierra el incidente (toma el mismo candado) sin aviso de "recuperado".
      - Los incidentes cerrados se borran al cumplir **1 año**, en el cron de limpieza.
    - **Outbox** (tabla `notifications`, migración `0004`):
      - un aviso `opened` / `resolved` por incidente, con estado `pending` / `sent` / `failed` / `skipped`;
      - el cron `deliver_notifications`, cada 5 s, reclama con `SKIP LOCKED` y una reserva de 60 s, hace commit y después envía: **sin conexión de BD abierta durante el envío**;
      - **cada envío acaba muy dentro de su reserva** (condición de Toni): un plazo total de 10 s por envío (`asyncio.timeout`, porque los timeouts de httpx2 son por fase) y cada aviso se reclama justo antes de enviarlo, de uno en uno. Un test comprueba que la reserva es al menos 3 veces el plazo y que un envío colgado se corta;
      - **solo se reintentan los fallos temporales** (decisión de Toni, 2026-11-09): red, timeout, 429 y 5xx, esperando 10 s y creciendo hasta 1 h, o lo que diga el `retry_after` del 429;
      - **un fallo permanente** (400, 401, 403, 404…: token inválido, chat inexistente, bot bloqueado) pasa a `failed` al momento, con un log ERROR que dice el problema, sin token ni URL. Punto débil: arreglar el token no recupera los avisos fallidos mientras tanto (los incidentes sí quedan en la API);
      - **los reintentos se rinden** tras 20 intentos o **24 h desde el primer intento** (columna `first_attempt_at`) → `failed`, con un log ERROR sin token ni URL. Si el siguiente reintento caería fuera de las 24 h, se rinde en ese momento;
      - **un aviso se descarta por inútil, nunca por viejo** (decisión de Toni, 2026-11-09): un DOWN con el incidente aún abierto se envía siempre (si no, una caída anterior a un parón del worker no avisaría nunca); un DOWN con el incidente ya cerrado pasa a `skipped` (el RECOVERED lleva inicio y duración; si se cerró por pausa o cambio de URL, lo hizo la propia persona); el RECOVERED se envía siempre;
      - "resuelto" **espera** mientras "abierto" siga `pending`;
      - sin bot configurado → `skipped`.
    - **Telegram:** Bot API directa con httpx2 detrás de `Notifier`. Dirección fija, `trust_env=False`, TLS verificado, texto plano.
    - **Mensaje:** nombre, `public_id`, `error_kind`, código HTTP, inicio y duración, en UTC. Nunca la URL ni el `error_detail`.
    - **`AlertSettings`** (solo worker): `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`, opcionales, los dos o ninguno. Comando `python -m pulseops.alerts test`.
    - **Anti-spam:** un mensaje por evento, respetando el 429, sin recordatorios.
    - **`GET /health/scheduler`** (sin API key): 200 `ok` si el último turno tiene menos de 60 s; 503 `stale`, o `unavailable` si la BD no responde en 3 s; JSON simple como `/health` (no RFC 9457), con `Cache-Control: no-store` (condición de Toni) y sin la hora. `/health` no cambia.
    - **API** (formas aprobadas el 2026-11-09):
      - `GET /api/v1/monitors/{id}/incidents` y `GET /api/v1/incidents?state=open|resolved` (lista cerrada, otro valor → 422);
      - páginas `{items, next_cursor}`; un incidente es `{id, started_at, resolved_at, error_kind, status_code, resolution}`; en la lista global, además, `monitor: {id, name}` (anidado);
      - sin campos calculados (`duration_seconds`, `state`): añadir es fácil, quitar rompe;
      - cursor opaco `base64url` de `i1:<µs>:<id del incidente>`, uno para las dos listas;
      - `open_incident` (`id`, `started_at`, `error_kind`, `status_code`) en `/stats`, detrás de `last_check`.
    - **Carril `alerts`** (límite 1); `checks` baja a 29. Se comprueba contra Valkey real.
  - Terminada cuando:
    - Toni recibe en Telegram el aviso de caída y el de recuperación, sin URL ni token en los mensajes ni en los logs;
    - el incidente se ve en la API, y una web que alterna no genera avisos sin parar;
    - con Telegram caído, el aviso se reintenta, respeta el orden y se rinde según la regla;
    - `/health/scheduler` da 503 con el worker parado;
    - Ruff, tests (cobertura ≥ 95 %) y CI en verde;
    - Toni lo prueba.
- **Fase 8 — Interfaz y métricas:** Grafana y/o HTMX; métricas Prometheus.
- **Fase 9 — Despliegue:** VPS, Nginx o Caddy, dominio, HTTPS, despliegue automático.
  - En el proxy: límite de tamaño de las peticiones y de intentos fallidos de API key.
  - Poner la API detrás del proxy y quitar su publicación en `127.0.0.1`.
  - Decidir `DOCS_ENABLED` en producción.
  - El SSRF ya contempla un VPS solo IPv6 con DNS64/NAT64.
  - `/health/scheduler` no lleva API key y consulta la BD: **necesita el límite de peticiones del proxy** (ADR-068).
  - Configurar un **vigilante externo** (uptime monitor o *dead man's switch*) que consulte `/health/scheduler` (ADR-068).
  - **Aviso global de "el problema somos nosotros"**: si caen muchos monitores a la vez, un solo aviso en vez de uno por monitor (ADR-067).
- **Fase 10 — Extras:** usuarios y login, página de estado pública, etc.
  - Sustituir la API key por usuarios.
  - Filtro por dueño en el repositorio, que es la única capa de acceso a datos.
  - La restricción `uq_monitors_url` pasa a ser única por `(owner_id, url)`.

---

## Convenciones

- **Ramas:** una por fase, en inglés (`phase-0-foundations`, `phase-1-data-model`…), fusionadas a `main` por PR. Desde el 2026-10-28 lo exige el ruleset de `main`: no se puede subir directamente.
- **Commits:** Conventional Commits en inglés (`feat:`, `fix:`, `chore:`, `docs:`, `test:`), pequeños y descriptivos, sin líneas de atribución y siempre con el OK previo de Toni (regla 15).
- **Idioma del proyecto: inglés.** Todo lo que vive en el repo va en inglés: código (nombres, comentarios, docstrings), README, `docs/decisions.md` y cualquier otra documentación, mensajes de commit, ramas, issues y Pull Requests.
- **Idioma de la conversación: español.** Las explicaciones, preguntas y resúmenes para Toni se dan en español.
- **Calidad:** todo el código pasa Ruff y pytest antes de cada PR. Tests para cada pieza con lógica.
- **Configuración:** variables de entorno (`.env`, con `.env.example` en el repo). Nunca subir secretos.
- **Decisiones:** cada una en `docs/decisions.md`.
- **Datos verificados** (tests, comprobaciones manuales, versiones, hallazgos): en `docs/evidence.md`.
- **README sin cifras del proyecto escritas a mano** (número de tests, cobertura, número de ADR, tiempos…), porque se quedan viejas: el README enlaza a `docs/evidence.md`. Las reglas de funcionamiento (30 s, 10 s, 30 días…) y los ejemplos reales sí van.

---

## Estado actual

- **Fase actual:** **Fase 7 — Alertas e incidentes**, en construcción en la rama `phase-7-alerts-and-incidents`. Plan aprobado por Toni el 2026-11-03, con ADR-059 a ADR-070.
- **Cambios descubiertos en Fase 7 (durante la construcción):**
  - **Convención de nombres:** los `uq_` llevan ahora todas sus columnas (`column_0_N_name`). Si no, el único de `(monitor_id, started_at)` se llamaría `uq_incidents_monitor_id`, como si `monitor_id` fuera único. Los nombres de una sola columna no cambian (`alembic check` limpio).
  - **`with_for_update(key_share=True)` de SQLAlchemy da `FOR NO KEY UPDATE`;** para `FOR KEY SHARE` hace falta además `read=True`. Hay un test que lo fija.
  - **El *autoflush* adelanta los errores:** cualquier sentencia guarda antes los cambios pendientes del ORM. Al cambiar la URL, cerrar el incidente *después* de tocar el monitor hacía saltar el `uq_monitors_url` fuera de `_commit` → un 500 en vez del 409 (lo detectó `test_patch_url_to_an_existing_one_is_a_conflict`). Ahora se cierra el incidente antes de tocar los campos.
  - **`store_check` lee el monitor con `FOR KEY SHARE`** antes de insertar: un monitor borrado ya no provoca un error de clave foránea que haya que capturar. `record_check` ya no hace commit ni captura ese error.
  - **Un test de concurrencia que no demostraba nada:** sin candado, las dos tareas acababan en orden y el test seguía pasando. Ahora cada `store_check` espera entre evaluar y hacer commit (con `monkeypatch`), y sin candado el test falla, como debe. Comprobado rompiendo el código a propósito: sin el candado, sin la regla del check tardío, sin `not_before`, con la pausa sin candado y con `FOR UPDATE`, su test falla en cada caso.
  - **httpx2 escribe la URL completa (con el token del bot) a nivel INFO,** también con `MockTransport`. `alerts/telegram.py` silencia httpx2 por su cuenta. **Dentro de pytest eso no se ponía a prueba:** al importar `pulseops.main` se carga el comprobador, que silencia httpx2 para todo el proceso. Ahora lo comprueba un test en un intérprete limpio, como corre `python -m pulseops.alerts test`.
  - **Con un *transport* inyectado, httpx2 ignora las variables de proxy.** Un test con `MockTransport` no podía demostrar `trust_env=False`; el test mira el cliente real.
  - **pydantic-settings lee `TELEGRAM_BOT_TOKEN=` (vacío) como texto vacío,** no como "sin poner", salvo con `env_ignore_empty=True`. Sin eso, el `.env.example` con valores vacíos impediría arrancar el worker.
  - **El nombre de un monitor admite saltos de línea** (la API solo limita la longitud). En los avisos se convierten en espacios, para que un nombre no pueda colar una línea falsa ("RECOVERED").
  - **`AlertSettings` pasa del paso 6 al 5:** el comando de prueba ya lo necesita.
  - **Respuestas reales de Telegram** (2026-11-09, con tokens inventados): un token con buena forma pero falso da `401 Unauthorized`; uno mal formado, `404 Not Found`. El 400 (chat inexistente) y el 403 (bot bloqueado) necesitan un bot real: **comprobarlos en la prueba manual (paso 9)**.
  - **Con tres carriles, `checks` en 30 deja al planificador sin hueco** (29 + 1 + 1 + el suyo = 32). Comprobado contra Valkey real.
  - **Los tests del worker fuerzan las alertas apagadas** (`AlertSettings` sustituido en el fixture): si el `.env` de desarrollo tuviera un token real, ningún test podría escribir a ese bot.
  - **Las 24 h de reintentos se cuentan desde el primer intento, no desde que se creó el aviso:** si no, un DOWN que esperó a un worker parado tendría un solo intento si Telegram fallaba justo entonces. Hizo falta la columna `first_attempt_at`, añadida en la propia `0004`, que aún no había salido de la rama (la BD de desarrollo se rehízo con `downgrade 0003` + `upgrade`; tenía 0 incidentes y 0 avisos).
  - **Conectar a un puerto local cerrado no siempre se rechaza al momento:** en la máquina de desarrollo, asyncpg se quedó colgado 60 s (su timeout de conexión) contra `127.0.0.1:1`. Es justo el caso que cubre el plazo de 3 s de `/health/scheduler`.
  - **`/health` se mueve a `api/health.py`,** junto a `/health/scheduler`, sin cambiar su comportamiento.
  - **El smoke test pasa de 29/29 en 6,5 s a 37/37 en unos 35 s:** el incidente necesita 2 checks fallidos con 30 s de intervalo. Su monitor se crea al principio para que el resto de la prueba corra mientras tanto.
  - **El smoke test no puede ver el reparto de avisos:** borra sus monitores (y en cascada sus avisos) antes del siguiente turno del cron. Comprobado aparte, de punta a punta: con las alertas apagadas, el aviso pasa a `skipped`.
  - **PyYAML** llega con `uvicorn[standard]` (dependencia de producción); un test lo usa para leer `docker-compose.yml` y comprobar que la API nunca recibe el token.
  - **El cron de reparto solo registra el *tipo* de un error inesperado,** no su mensaje: un fallo del canal podría citar la URL de la Bot API, que lleva el token.
- **Antes:** MVP completo con la release v0.1.0 (2026-10-28) y el repo **público**. Fase 6 cerrada (PR #7 y PR #11). Después vinieron el repaso de seguridad (PR #12), las dependencias de Dependabot (PR #13 y #14) y la documentación de ArdiQ 1.2.1 (PR #15).
- **Hecho en Fase 6:**
  - `.github/workflows/ci.yml` con los jobs `lint`, `test` y `stack`, en verde en GitHub;
  - prueba del rojo: PR #8, cerrado sin fusionar, con los logs del fallo revisados;
  - `scripts/ci_env.py`;
  - imágenes fijadas por digest y acciones por SHA, con Dependabot para `github-actions`;
  - suelo de cobertura del 95 %;
  - `log_error_verbosity=terse` en PostgreSQL (ADR-044);
  - README de escaparate con capturas, y licencia MIT;
  - 267 tests;
  - ADR-053 a ADR-058;
  - **al cerrar:**
    - escaneo con `gitleaks` de todo lo que hay en GitHub (ramas y PR): un solo hallazgo, un falso positivo (la clave inventada de los tests), apuntado en `.gitleaksignore`;
    - etiqueta `v0.1.0` y release "v0.1.0 — MVP";
    - Dependabot ignora los saltos menores y mayores de Python (PR #10 cerrado);
    - la versión de uv sale solo del Dockerfile (CI la lee de ahí) y sube a 0.13.6, lo mismo que proponía el PR #9. Dependabot cerró el #9 solo al ver uv al día;
    - Toni pasó el repo a público y activó: escaneo de secretos con push protection, alertas de Dependabot y PR de seguridad automáticos, y el ruleset de `main`. Comprobado por la API.
- **Cambios descubiertos en Fase 6 (durante la construcción):**
  - **PostgreSQL escribía las URLs en su log de errores.** Al repetir una URL salía `DETAIL: Key (url)=(<URL>) already exists`, y en una CHECK, la fila entera. Lo escribe el propio servidor, no nuestro código. Arreglado con `log_error_verbosity=terse` (ADR-044) y un test.
  - **Docker Hub limita las consultas anónimas a 100 por hora** (cabecera `ratelimit-limit: 100;w=3600`). Inspeccionar digests con `docker buildx imagetools inspect` gasta varias por imagen. Los runners de GitHub descargan sin problema.
  - **`docker compose up --wait` acepta que `migrate` termine con 0** (y falla si `migrate` falla). Verificado con Compose v5.6.1.
  - **Valkey pasa de 9.1.2 a 9.1.3** al fijar las imágenes: es lo que publicaba `valkey/valkey:9` el 2026-10-28. PostgreSQL sigue en 18.6 y Python en 3.13.18.
  - **`python:3.13-slim` y `python:3.13.18-slim` tienen digests de índice distintos,** pero las mismas imágenes por plataforma (amd64 y arm64 coinciden). Se fija la pareja exacta etiqueta + digest.
  - **Los avisos "Failed to save: Unable to reserve cache" de `setup-uv`** aparecen cuando dos jobs intentan guardar la misma caché a la vez. Son inofensivos: uno de los dos la guarda.
  - **El diagrama Mermaid** no se puede comprobar desde la terminal: GitHub lo dibuja en el navegador. Toni confirmó el 2026-10-28 que se dibuja bien.
  - **Dependabot entiende los pines por digest:** su primer PR (#9) subió uv cambiando etiqueta y digest a la vez, en la etapa `AS uv`. También propuso Python 3.15 (#10), y CI lo paró: la imagen ya no construía.
  - **`gh pr edit` falla en este repo** por un error de GraphQL con los Projects antiguos de GitHub. Los PR se editan con la API REST (`gh api -X PATCH repos/3fxsty/pulseops/pulls/N`).
  - **En el equipo de desarrollo, uv sigue en 0.13.5;** la imagen y CI usan 0.13.6. Si se quiere igualar: `uv self update`.
- **Hecho en Fase 5:**
  - `GET /api/v1/monitors/{id}/checks` (historial con cursor opaco) y `GET /api/v1/monitors/{id}/stats` (estado actual, uptime, media y p95, recuentos);
  - `pulseops/status.py`, `pulseops/timestamps.py` y `api/cursors.py`;
  - la retención (`pulseops/retention.py`): un cron cada hora en el carril `maintenance`, por lotes y por `ctid`, con un tope de 60 s;
  - `build_app` en `queue/app.py`;
  - `scripts/measure_queries.py`;
  - el smoke test con 29 casos;
  - 266 tests (cobertura del 97 %);
  - ADR-046 a ADR-052.
- **Cambios descubiertos en Fase 5 (durante la construcción):**
  - **Medición** (`scripts/measure_queries.py`, 10 monitores, 892 810 checks): `/stats` de 30 días tarda unos 20 ms y el historial unos 1,7 ms por página, así que calcular al vuelo basta.
  - **El borrado por lotes no era estable con `(monitor_id, scheduled_at) IN (subconsulta)`.**
    - Según la muestra de estadísticas, PostgreSQL elegía un *hash join* con `Seq Scan` de la tabla entera: 99 ms por lote, y crecería con la tabla.
    - **Ahora se borra por `ctid`** (la dirección física de la fila): `ctid = ANY(ARRAY(SELECT ctid … LIMIT 5000)) AND scheduled_at < corte` y un `Tid Scan`, sin cruce.
    - **La fecha se vuelve a comprobar en el propio `DELETE`** (condición de Toni): si una dirección apuntara a un check reciente, no se borra. La selección y el borrado van en la misma sentencia; hay un test que lo simula.
    - En 5 ejecuciones, ningún `Seq Scan`.
  - **Qué índice usa el borrado:**
    - con atraso usa el BRIN;
    - en el borrado normal de cada hora, PostgreSQL 18 elige la PK con *skip scan* (una búsqueda por monitor): 0,7 ms con 10 monitores y 4,8 ms con 1 000;
    - el paso al BRIN con muchos más monitores no está verificado. Se deja elegir al planificador.
  - **El carril `maintenance` exigía bajar `checks` a 30.** Con `checks` en 31 y la limpieza ocupando 1, el planificador no se ejecutaba (comprobado contra Valkey real).
  - **`pulseops/timestamps.py`:** las funciones de microsegundos salen de `queue/tasks.py`, porque si la API importara ese módulo se crearía la app de ArdiQ, que necesita `BROKER_URL`, y la API ya no la tiene.
  - **Solo el dueño de una tabla puede ejecutar `ANALYZE`:** el script lo hace como `pulseops_owner`. En producción lo hace el autovacuum.
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
    - **2026-10-28, desde otra casa (otro router):** falla igual (conexión cortada en ~40 ms, con `curl` y con el comprobador). Con dos redes distintas fallando igual, el router queda descartado: la causa está en el proveedor de internet (si es el mismo en las dos casas) o en el propio equipo de desarrollo (Windows/WSL, antivirus). El resto del stack funciona igual en la red nueva: tests 266/266 y smoke test 29/29.
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
- **Repaso de seguridad previo a la Fase 7 (PR #12, fusionado):**
  - `SECURITY.md` añadido (versiones 0.1.x, aviso por *Report a vulnerability*, respuesta en 7 días como objetivo).
  - `DOCS_ENABLED` pasa a `false` por defecto (código y Compose); `.env.example` lo pone a `true` para desarrollo (ADR-027, enmienda).
  - Aviso en el README: no exponer a internet hasta la Fase 9.
  - Toni activó *Private vulnerability reporting* y CodeQL (default setup); comprobado por la API.
  - 269 tests.
  - El 2026-11-03: 0 alertas abiertas de CodeQL, Dependabot y secret scanning.
- **Dependabot tras el repaso (2026-11-03):** PR #13 (`setup-uv` 10.3.3) y PR #14 (ArdiQ 1.2.1, pydantic-settings 2.16.2, pytest 9.2.0, Ruff 0.17.3), fusionados con CI en verde.
- **Notas para más adelante:**
  - En el VPS (Fase 9), activar `vm.overcommit_memory = 1` en el host, que Valkey lo pide en sus logs.
  - `restart: unless-stopped` solo sirve tras reiniciar el equipo si el demonio de Docker arranca solo. En el VPS (Fase 9), comprobarlo (`systemctl is-enabled docker`).
  - Si la tabla `checks` crece mucho, particionarla por fecha o pasar a TimescaleDB. La PK `(monitor_id, scheduled_at)` ya está preparada para ello.
- **Siguiente paso** (Fase 7, en pasos pequeños y con cada commit enseñado antes):
  1. ✅ ADRs y este archivo.
  2. ✅ Migración `0004` (`incidents`, `notifications`) y modelos, revisada a mano.
  3. ✅ `pulseops/incidents.py` (la regla pura).
  4. ✅ Repositorios y `run_check` (candado, check tardío), y cierre al pausar o cambiar la URL.
  5. ✅ `pulseops/alerts/` (`Notifier`, `TelegramNotifier`, mensaje, comando de prueba) y `AlertSettings`.
  6. ✅ Cron `deliver_notifications` (`pulseops/delivery.py`), carril `alerts`, solo reintentos temporales y retención de los incidentes de 1 año.
  7. ✅ API de incidentes (`api/incidents.py`, cursor `i1`), `open_incident` en `/stats` y `/health/scheduler` (`api/health.py`, con `Cache-Control: no-store`).
  8. ✅ Compose (Telegram solo para el worker, opcional), `.env.example` (vacías = apagadas), README (sección "Incidents and alerts", rutas, diagrama), smoke test (37 casos) y verificaciones en `docs/evidence.md`. **Al cerrar la fase:** fila de la Fase 7 y desglose de tests en `docs/evidence.md`.
  9. Prueba manual de Toni con un bot real; antes, explicarle paso a paso cómo crear el bot con BotFather y sacar el `chat_id`.
