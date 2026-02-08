# Python 3.11 slim image for smaller container size
FROM python:3.11-slim

# Install Stockfish chess engine
RUN apt-get update && \
    apt-get install -y --no-install-recommends stockfish && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install Python dependencies first (for Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install gunicorn for production server
RUN pip install --no-cache-dir gunicorn

# Copy application code
COPY . .

# Environment variables
ENV STOCKFISH_PATH=/usr/games/stockfish
ENV STOCKFISH_THREADS=2
ENV PORT=8000

# Expose port
EXPOSE 8000

# Run with gunicorn (production-ready WSGI server)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "app:app"]
