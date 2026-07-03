FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# cache-bust: Railway kept redeploying a stale image (same digest) instead of rebuilding the
# source layer. Bump this token to force a real rebuild that picks up the latest src/.
RUN echo "cachebust 2026-07-02-pendingfile-dup"
COPY . .
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
EXPOSE 8080
CMD uvicorn src.server:app --host 0.0.0.0 --port ${PORT:-8080}
