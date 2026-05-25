# syntax=docker/dockerfile:1.7
#
# PartSelect chat agent backend.
#
# Multi-stage build:
#   - builder: install dependencies into /opt/venv against pyproject.toml.
#   - runtime: copy /opt/venv + source into a slim image, run as non-root.
#
# Production install excludes the [retrieval] and [pii] extras to keep the
# image small (~250MB instead of ~1.5GB with torch). Those land when
# Phase 2 and Phase 4 ship.

ARG PYTHON_VERSION=3.12-slim-bookworm

# ------------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tools for any wheels that need compilation. Postgres client libs are
# bundled in psycopg-binary so we do NOT need libpq-dev.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Cache deps independent of source changes.
WORKDIR /build
COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install .

# Now copy the source and install the package itself (no deps re-resolved).
COPY app ./app
RUN pip install --no-deps .

# ------------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PORT=8000 \
    LOG_LEVEL=INFO

# curl for the HEALTHCHECK + libgomp1 in case any wheel needs it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --home-dir /app --create-home app

COPY --from=builder --chown=app:app /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app app ./app
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app data ./data
# pyproject.toml so `python -c "import importlib.metadata; ..."` works.
COPY --chown=app:app pyproject.toml ./

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

# Single worker is fine for v1: LangGraph + httpx are async and the
# concurrency ceiling is the LLM provider, not the FastAPI process.
# Bump to `--workers 2` once we're traffic-bound.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
