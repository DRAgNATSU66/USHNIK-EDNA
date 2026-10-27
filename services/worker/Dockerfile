FROM python:3.11-slim

# Docker's non-TTY stdout is fully block-buffered by default, so the
# dispatcher's print() calls (startup, job completion) could sit unflushed
# indefinitely -- `docker logs` looked empty even though the process was
# running fine.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# BLAST+ (mounted from <data root>/tools/blast) links against OpenMP; the slim
# image lacks it, and blastn exits 127 ("libgomp.so.1: cannot open shared
# object file"), so the reference lookup came back unavailable on every route.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Route heads need torch + transformers; without them every sequence is a
# stub (stub_reason torch_unavailable). CPU wheels by default: Docker on a
# host without the NVIDIA container runtime has no GPU anyway. For a GPU
# deployment build with
#   --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130
# Build with --build-arg WITH_ML=0 for the old stub-only image.
ARG WITH_ML=1
ARG TORCH_VERSION=2.14.1
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
COPY requirements-ml.txt .
RUN if [ "$WITH_ML" = "1" ]; then \
      pip install --no-cache-dir --index-url "$TORCH_INDEX_URL" "torch==$TORCH_VERSION" \
      && pip install --no-cache-dir -r requirements-ml.txt; \
    fi

# DNABERT-2 is loaded with trust_remote_code, which writes its modeling code
# into the Hugging Face modules cache. The worker user has no home directory
# and /data is mounted read-only, so the cache lives in /tmp.
ENV HF_HOME=/tmp/hf_home

COPY app/ ./app/

# Non-root user for container security
RUN useradd --no-create-home --shell /sbin/nologin synthveda
USER synthveda

HEALTHCHECK --interval=60s --timeout=15s --start-period=30s --retries=3 \
  CMD python -c "from app.dispatcher import health_check; health_check()" || exit 1

CMD ["python", "-m", "app.dispatcher"]
