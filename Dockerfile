FROM python:3.12-slim

WORKDIR /app

# Install system deps (curl needed for health probes)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install uv

# Copy dependency definition
COPY backend/pyproject.toml .

# Install dependencies
RUN uv pip install --system -r pyproject.toml

# Copy application code
COPY backend/ .
COPY scripts/ /app/scripts/

# Create output directories
RUN mkdir -p /app/output /app/logs

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Cloud Run injects PORT; fallback to 5001 for local dev
ENV PORT=5001
EXPOSE ${PORT}

CMD ["python", "-m", "app.main"]

