# syntax=docker/dockerfile:1

# ---- 1) build the React SPA
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2) runtime: FastAPI serves the API and the built SPA
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TORUB_DB=/data/torobticket.db
WORKDIR /app/backend
COPY backend/requirements.txt ./
# pytest is a dev dependency; keep it out of the image
RUN grep -v '^pytest' requirements.txt > /tmp/req.txt && pip install --no-cache-dir -r /tmp/req.txt
COPY backend/ ./
# app/main.py looks for ../frontend/dist relative to the backend folder
COPY --from=frontend /build/dist /app/frontend/dist
# Host files can arrive with owner-only permissions (700/600) that the non-root user can't read,
# which shows up as 'Could not import module "app.main"'. Normalise before dropping privileges.
RUN chmod -R a+rX /app && useradd --system --uid 10001 app && mkdir /data && chown app /data
USER app
# Fail the build (with a full traceback) instead of shipping an image that crash-loops at start.
RUN TORUB_DB=/tmp/build-check.db python -c "import app.main" && rm -f /tmp/build-check.db
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2).status==200 else 1)"
# Worker processes come from WEB_CONCURRENCY (default 1). Use more than one only with Postgres
# (TORUB_DATABASE_URL) and Redis (TORUB_REDIS_URL), which the processes share.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "10"]
