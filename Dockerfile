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
EXPOSE 8000

# Run the FastAPI server
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
