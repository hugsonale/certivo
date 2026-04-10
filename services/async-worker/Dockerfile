FROM python:3.11-slim

WORKDIR /app

# Install OpenCV dependencies
RUN apt-get update && apt-get install -y \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]