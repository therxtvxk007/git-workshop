# Multi-stage: the runtime image carries no compiler and no test dependencies.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libgomp1 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY pramaan_x ./pramaan_x
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install ".[boost,serve,llm]"

# ---------------------------------------------------------------- runtime ---
FROM python:3.12-slim AS runtime

# libgomp is required by LightGBM and XGBoost at runtime; without it the import
# succeeds and the first fit segfaults, which is a miserable thing to debug.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 curl && rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 pramaan

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=4

WORKDIR /app
COPY --chown=pramaan:pramaan pramaan_x ./pramaan_x
COPY --chown=pramaan:pramaan configs ./configs
RUN mkdir -p /app/artifacts /app/.cache && chown -R pramaan:pramaan /app

USER pramaan
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "pramaan_x.api:app", "--host", "0.0.0.0", "--port", "8000"]
