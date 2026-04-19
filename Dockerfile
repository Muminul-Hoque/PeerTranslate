FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (required for onnxruntime and layout vision)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Run the server
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
