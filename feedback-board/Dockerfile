# Build context MUST be the repo root (not feedback-board/) so we can copy in a
# fresh read-only snapshot of the KB and the section skill prompts:
#
#   docker build -f feedback-board/Dockerfile -t feedback-board .
#
# On Railway: set this service's Root Directory to the repo root and the Dockerfile
# path to feedback-board/Dockerfile. Every push then bakes the current kb/ +
# src/skills/ into the image — the chat's knowledge stays as fresh as the deploy.
FROM python:3.13-slim

WORKDIR /app

COPY feedback-board/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY feedback-board/src/ ./src/
COPY feedback-board/static/ ./static/

# Read-only snapshots consumed by the chat (Phase 3). Isolated copies — the
# service never imports or mutates the main program.
COPY kb/ ./kb/
COPY src/skills/ ./skills/

EXPOSE 8080

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
