# The Python API and the scheduled worker share this image: same code, same
# migrations, different entrypoint.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libpq for psycopg, and nothing else: a smaller image is a smaller attack surface.
RUN apt-get update \
 && apt-get install --no-install-recommends -y libpq5 \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic
COPY seed ./seed
COPY scripts ./scripts
COPY app ./app

# Never run as root, and give the file store a writable home.
RUN useradd --create-home --uid 10001 fms \
 && mkdir -p /app/var/files \
 && chown -R fms:fms /app
USER fms

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
