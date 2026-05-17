FROM python:3.12-slim

WORKDIR /app

# System deps for python-whois, dnspython, lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    whois \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY domain_intel/ ./domain_intel/
COPY api/ ./api/
COPY scripts/ ./scripts/

# Create data dirs
RUN mkdir -p /app/data/cache

EXPOSE 8080

# Default: run the API server
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8080"]
