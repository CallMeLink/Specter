FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt sherlock-project

COPY . .

ENV PORT=8000
ENV HOST=0.0.0.0

EXPOSE 8000

CMD uvicorn src.backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
