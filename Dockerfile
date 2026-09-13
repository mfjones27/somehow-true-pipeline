FROM python:3.12-slim

# Install ffmpeg (required for video encoding, ffprobe, loudness measurement)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-lato \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline code
COPY . .

# Default port for Railway
ENV PORT=8000
ENV PIPELINE_ENABLED=false PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000

# app.py reads Railway's PORT; no shell expansion or generation at startup.
CMD ["python", "app.py"]
