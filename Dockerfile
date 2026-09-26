# ODYSSEY TRANSFORM CORE - single-image deployment.
#
# Stage 1 builds the dashboard, stage 2 serves it from FastAPI so the whole
# product is one origin on one port. The backend looks for the bundle at
# <repo>/frontend/dist, which is where stage 2 puts it.
#
#   docker build -t odyssey-transform-core .
#   docker run -p 8000:8000 odyssey-transform-core

# ---- Stage 1: dashboard ----------------------------------------------------
FROM node:22-alpine AS web

WORKDIR /build

# Dependencies first so a source-only change reuses the cached install layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---- Stage 2: application --------------------------------------------------
FROM python:3.12-slim AS runtime

# tesseract-ocr + poppler-utils back the OCR path; curl backs the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY backend/drop_privs.py /usr/local/bin/drop_privs.py

# main.py resolves the dashboard at parents[2]/frontend/dist from app/main.py.
COPY --from=web /build/dist /srv/app/frontend/dist

# Unprivileged application user. The entrypoint starts as root only long enough
# to make a late-mounted volume writable, then drop_privs.py execs the server as
# this user, so the server is still PID 1 and still receives SIGTERM directly.
RUN useradd --create-home --uid 10001 --user-group odyssey \
    && mkdir -p /srv/app/data /srv/app/data/uploads \
    && chown -R odyssey:odyssey /srv/app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

# The database and the uploaded originals share one volume, so a redeploy
# cannot keep the ledger while losing the sources that ledger attests to.
ENV DATA_DIR=/srv/app/data \
    UPLOAD_DIR=/srv/app/data/uploads

ENV HOST=0.0.0.0 \
    PORT=8000 \
    ENVIRONMENT=production \
    DATABASE_URL=sqlite:////srv/app/data/odyssey.db \
    ALLOW_PRIVATE_NETWORK_FETCH=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${HOST} --port ${PORT}"]
