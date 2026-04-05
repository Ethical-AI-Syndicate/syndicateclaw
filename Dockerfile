# ---------- base ----------
FROM python:3.14.3-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --create-home app

WORKDIR /app

# ---------- builder ----------
FROM base AS builder

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# ---------- runtime ----------
FROM base AS runtime

COPY --from=builder /install /usr/local

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["uvicorn", "syndicateclaw.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
