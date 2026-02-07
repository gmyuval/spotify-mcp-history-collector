FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install shared package requirements first (better layer caching)
COPY shared/requirements.txt ./shared_requirements.txt
RUN pip install --no-cache-dir -r shared_requirements.txt

# Copy and install service requirements
COPY api/requirements.txt api/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy shared package source
COPY shared/src/ ./shared_src/

# Copy application code
COPY api/src/ ./src/
COPY api/alembic/ ./alembic/
COPY api/alembic.ini ./

# Set Python path (shared_src first so shared is importable)
ENV PYTHONPATH=/app/src:/app/shared_src

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose.yml)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
