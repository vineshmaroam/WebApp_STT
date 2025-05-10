# Use an official Python runtime as base
# FROM python:3.11-slim
FROM python:3.11

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \  # For audio processing
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN python -m pip install --upgrade pip

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables (or use Kubernetes Secrets)
ENV FLASK_APP=main.py
ENV FLASK_ENV=production
ENV MONGODB_URI=your_mongodb_uri
ENV GOOGLE_CREDENTIALS=your_google_credentials_json
ENV PROJECT_ID=your_gcp_project_id
ENV GOOGLE_API_KEY=your_google_api_key

# Expose the Flask port (default: 8080)
EXPOSE 8080

# Run the Flask app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]