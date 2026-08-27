FROM python:3.11-slim

# See services/worker/Dockerfile for why this matters -- same buffering
# gotcha applies to any print()/logging that isn't routed through uvicorn.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Non-root user for container security. /app/uploads must exist and be
# owned by that user BEFORE the switch: it's a named-volume mount point
# (uploads_data:/app/uploads in docker-compose.yml), and Docker initializes
# a fresh named volume's ownership from whatever the mount point already
# has in the image layer at first mount -- created it as root (the default)
# and the app user couldn't write to it, failing every upload with
# PermissionError: [Errno 13] Permission denied.
RUN useradd --no-create-home --shell /sbin/nologin synthveda \
    && mkdir -p /app/uploads \
    && chown -R synthveda:synthveda /app/uploads
USER synthveda

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
