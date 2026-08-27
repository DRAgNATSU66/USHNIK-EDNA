FROM python:3.11-slim

# Docker's non-TTY stdout is fully block-buffered by default, so the
# dispatcher's print() calls (startup, job completion) could sit unflushed
# indefinitely -- `docker logs` looked empty even though the process was
# running fine.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Non-root user for container security
RUN useradd --no-create-home --shell /sbin/nologin synthveda
USER synthveda

HEALTHCHECK --interval=60s --timeout=15s --start-period=30s --retries=3 \
  CMD python -c "from app.dispatcher import health_check; health_check()" || exit 1

CMD ["python", "-m", "app.dispatcher"]
