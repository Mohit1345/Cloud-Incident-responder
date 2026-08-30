FROM python:3.12-slim

WORKDIR /app

# docker CLI is needed to restart the app container after apply_lock_fix.
# Requires /var/run/docker.sock to be mounted at runtime (see docker-compose.addon.yml).
RUN apt-get update && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY patches/ ./patches/

EXPOSE 8002

CMD ["python", "server.py"]
