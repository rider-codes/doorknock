# The public, bring-your-own-key Doorknock: one container serves the page and the API.

# ---- 1. build the page ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Where the GitHub button points; override with --build-arg VITE_GITHUB_URL=https://github.com/you/your-fork
ARG VITE_GITHUB_URL=https://github.com/rider-codes/doorknock
ENV VITE_GITHUB_URL=$VITE_GITHUB_URL
RUN npm run build

# ---- 2. run it ----
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist

# Public mode: a private workspace per visitor, visitors' own keys only, Gmail / portals / auto-refresh off.
ENV PUBLIC_MODE=1 \
    DOORKNOCK_DATA=/data \
    EMBEDDINGS=hash \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data && useradd --create-home app && chown -R app /data /app
USER app

WORKDIR /app/backend
EXPOSE 8100
# Most hosts tell the app which port to use in $PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8100}"]
