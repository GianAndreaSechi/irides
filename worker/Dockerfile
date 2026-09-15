FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONPATH=/app

# Worker depends only on core — no api package needed
COPY core/ /app/core/
COPY worker/ /app/worker/

RUN pip install --no-cache-dir -r /app/core/requirements.txt \
 && pip install --no-cache-dir -r /app/worker/requirements.txt

CMD ["python", "-m", "worker.irides_worker.main"]
