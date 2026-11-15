FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONPATH=/app

COPY core/ /app/core/
COPY cli/ /app/cli/

# Install core with optional drivers first, then the CLI.
RUN pip install --no-cache-dir -r /app/core/requirements.txt \
 && pip install --no-cache-dir -e /app/core \
 && pip install --no-cache-dir --no-deps -e /app/cli

ENTRYPOINT ["irides"]
CMD ["configurations"]
