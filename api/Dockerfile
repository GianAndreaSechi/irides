# Use an official Python runtime as a parent image
FROM python:3.11-slim-bookworm

# Set the working directory in the container
WORKDIR /app

# Set PYTHONPATH to include the /app directory
ENV PYTHONPATH=/app

# Copy only the necessary components
COPY core /app/core
COPY api /app/api

# Install the core package in editable mode
RUN pip install --no-cache-dir -e /app/core

# Install remaining dependencies for the API
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Expose the port that FastAPI runs on
EXPOSE 8000

# Command to run the FastAPI application
CMD ["uvicorn", "api.irides_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
