FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt requirements-dev.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Set Python path
ENV PYTHONPATH=/app/src

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Expose port
EXPOSE 8002

# Default command (can be overridden in docker-compose.yml)
CMD ["uvicorn", "explorer.main:app", "--host", "0.0.0.0", "--port", "8002"]
