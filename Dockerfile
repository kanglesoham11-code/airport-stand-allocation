FROM python:3.10-slim

WORKDIR /app

# Install dependencies first for Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY stand_allocation/ stand_allocation/
COPY data/ data/
COPY Makefile .

# Generate deterministic test data (safe to re-run).
RUN python -m stand_allocation.generate_data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["python", "-m", "uvicorn", "stand_allocation.api:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-keep-alive", "5", "--limit-concurrency", "100"]

