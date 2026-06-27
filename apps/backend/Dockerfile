# Ledgerline backend image. Multi-stage: build wheels, then a slim runtime that
# runs as a non-root user.

FROM python:3.12-slim AS builder

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --upgrade pip build \
    && python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime

# Create an unprivileged user; financial services must not run as root.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LEDGERLINE_ENVIRONMENT=production

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels ledgerline-backend \
    && rm -rf /wheels

USER appuser
EXPOSE 8000

# A failing healthcheck signals orchestration to restart the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/v1/health').status==200 else 1)"

CMD ["uvicorn", "ledgerline_backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
