FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY constraints-security.txt ./
# Upgrade the build tooling, enforce transitive security floors, then remove pip
# (including its vendored libraries) from the runtime image.
RUN pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" \
    && pip install --no-cache-dir -e . -c constraints-security.txt \
    && pip check \
    && pip uninstall --yes pip

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN groupadd --gid 10001 finsight \
    && useradd --uid 10001 --gid 10001 --no-log-init --create-home \
        --shell /usr/sbin/nologin finsight \
    && install -d -o 10001 -g 10001 -m 0700 /app/uploads

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
