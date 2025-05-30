# Speech Transcription Web App with Google TTS

A Flask web application that transcribes audio files using DeepGram's speech-to-text (STT) and converts text to speech (TTS) using Google's TTS API.

![App Screenshot](https://github.com/user-attachments/assets/8e87797a-0d79-4462-b704-3de1a5180aa4)
![WebApp_done](https://github.com/user-attachments/assets/bde83a6d-44e2-4f10-8950-7e3eb3cf8031)

## Key Features

- **Audio Transcription**
  - Upload WAV/MP3/FLAC files
  - Real-time transcription with word-level confidence scores
  - Supports long audio files (chunked processing)
- **Text-to-Speech Playback**
  - Google TTS integration
  - Audio preview and download
- **User Authentication**
  - Secure login/registration
  - Personal phrase sets for improved accuracy

## Technologies

- **Backend**: Python (Flask)
- **Frontend**: HTML, CSS, JavaScript
- **Database**: MongoDB
- - **APIs**:
  - [Deepgram STT](https://developers.deepgram.com/docs/speech-recognition)
  - [Google TTS](https://cloud.google.com/text-to-speech)

## Setup

### Prerequisites

- Python 3.8+
- MongoDB Atlas or local MongoDB instance
- Deepgram API key 
- FFmpeg (for audio processing)
- ngrok (for the webhook)

### Installation

1. Clone the repository:
   ```bash
   git clone [https://github.com/yourusername/speech-app.git](https://github.com/vineshmaroam/WebApp_STT.git)
   cd speech-app
   # Create virtual environment
    python -m venv venv
    source venv/bin/activate  # Linux/Mac
    .\venv\Scripts\activate  # Windows

    # Install dependencies
    pip install -r requirements.txt

    # Install and start the ngrok server, to get the forwarding https URL
     ngrok http 8000 
    
### Configuration
```
  Create/update credentials .env file:

      DEEPGRAM_API_KEY=your_deepgram_key_here
      MONGODB_URI=mongodb_connection_string
      ENV APP_URL=https://<your generated url>.ngrok-free.app

  OR Update them in the Dockerfile

      ENV MONGODB_URI=mongodb_connection_string
      ENV DEEPGRAM_API_KEY=your_deepgram_key_here
      ENV APP_URL=https://<your generated url>.ngrok-free.app
```
### Deploy the webapp

```
    docker build --no-cache -t speech-to-text-app .
    docker run -p 8080:8080 --env-file .env speech-to-text-app
```
### Open the WebApp

    http://localhost:8080/login
    OR
    https://<your generated url>.ngrok-free.app
