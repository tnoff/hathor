# Dockerfile for Hathor
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Create directories for data
RUN mkdir -p /data/config /data/db /data/podcasts

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install hathor
RUN pip install --no-cache-dir -e .

# Set environment variables for XDG directories
ENV XDG_CONFIG_HOME=/data/config
ENV XDG_DATA_HOME=/data/db
ENV PYTHONUNBUFFERED=1

# Create entrypoint script
RUN echo '#!/bin/bash\n\
# Initialize config if it doesn'\''t exist\n\
if [ ! -f /data/config/hathor/config.yml ]; then\n\
    echo "No config found, running hathor init..."\n\
    hathor init --podcast-dir /data/podcasts --database /data/db/hathor/hathor.db\n\
    echo ""\n\
    echo "Config created at /data/config/hathor/config.yml"\n\
    echo "Edit this file to add your Google API key for YouTube support"\n\
fi\n\
\n\
# Run the command\n\
exec "$@"\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["hathor", "--help"]
