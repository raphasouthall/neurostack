# SPDX-License-Identifier: Apache-2.0
# NeuroStack Cloud — Multi-stage Docker build for GCP Cloud Run
#
# Build:  docker build -f cloud/Dockerfile -t neurostack-cloud .
# Run:    docker run -p 8080:8080 --env-file cloud/.env neurostack-cloud

FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/

# Install with api + cloud extras
RUN uv pip install --system ".[api,cloud]"

FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src /app/src

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

ENTRYPOINT ["uvicorn", "neurostack.cloud.api:app", "--host", "0.0.0.0", "--port", "8080"]
