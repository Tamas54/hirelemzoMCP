FROM python:3.12-slim

WORKDIR /app

# Persistent SQLite lives here on Railway via volume mount
RUN mkdir -p /data
ENV DB_PATH=/data/echolot.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "start.py"]
