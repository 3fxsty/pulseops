# Images are pinned by digest: a tag can be moved to other content, a digest
# cannot. With a digest the tag is only a label; Dependabot updates both.

# A named stage, so Dependabot sees it as an image (it reads FROM lines).
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

# The base image ships ca-certificates, which httpx2 needs: it verifies TLS
# against the OS trust store (via truststore). Keep them if the base changes.
FROM python:3.13.18-slim@sha256:76baad6037690d6e8c4397fbcaef17bca6f19eecef822b708fe8fa3417d30bb5

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first, in their own layer, so code changes don't
# trigger a full reinstall.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

CMD ["uvicorn", "pulseops.main:app", "--host", "0.0.0.0", "--port", "8000"]
