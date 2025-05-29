FROM python:3.11

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y ffmpeg libavcodec-extra libasound2-dev && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN python -m pip install --upgrade pip

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables
ENV FLASK_APP=main.py
ENV FLASK_ENV=production
ENV MONGODB_URI=
ENV DEEPGRAM_API_KEY=
ENV APP_URL=

EXPOSE 8080

# Run the Flask app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
