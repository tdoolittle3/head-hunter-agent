# The signed-in server (head_hunter/server.py), not the `adk web` dev UI.
# Deployed with `make deploy-test` / `make deploy-prod`; see docs/DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# google-adk is pinned once, in the repo-root requirements.txt, and read from
# there so this file cannot drift from it. The rest comes from the container
# list, which tests/test_requirements_in_sync.py keeps in step with the root.
COPY requirements.txt /tmp/requirements.txt
COPY head_hunter/requirements.txt /tmp/container-requirements.txt
RUN grep -E '^google-adk==' /tmp/requirements.txt > /tmp/adk.txt \
    && pip install -r /tmp/adk.txt -r /tmp/container-requirements.txt

COPY head_hunter/ /app/head_hunter/

# Run as nobody-in-particular: the app needs no write access to /app.
RUN useradd --create-home --uid 10001 app
USER app

# Cloud Run supplies PORT. Shell form so ${PORT} expands; exec so signals reach
# the server and a deploy can drain it cleanly.
CMD exec python -m uvicorn head_hunter.server:create_app --factory \
    --host 0.0.0.0 --port ${PORT:-8080}
