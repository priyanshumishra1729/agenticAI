# ---- 1. build the React UI -------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Python runtime (FastAPI + ADK + CrewAI + MCP) ----------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CREWAI_DISABLE_TELEMETRY=true \
    OTEL_SDK_DISABLED=true \
    FRONTEND_DIST=/app/frontend/dist \
    DATABASE_URL=sqlite:////data/signalchain.db \
    UPLOAD_DIR=/data/uploads \
    PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN mkdir -p /data/uploads && useradd -m appuser && chown -R appuser /data /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
