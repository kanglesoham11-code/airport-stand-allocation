FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first for Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and sample data.
COPY stand_allocation/ stand_allocation/
COPY data/ data/
COPY Makefile .
COPY .env.example .env.example

# Generate deterministic test data (safe to re-run).
RUN python -m stand_allocation.generate_data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')" || exit 1

CMD ["sh", "-c", "python -m uvicorn stand_allocation.api:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 5 --limit-concurrency 100"]

