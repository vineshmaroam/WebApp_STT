# Speech Transcription Web App with DeepGram Aura TTS

A Flask web application that transcribes audio files using DeepGram Aura's speech-to-text (STT) and converts text to speech (TTS) using it's TTS API. Though DeepGram Aura combines real-time STT with built-in LLM processing, there is also an LLM (Mistral-8x7B as the LLM processor) that is used to enhance the transcriptions.

![Architecture](https://github.com/user-attachments/assets/8edb3cee-e155-4a93-a20c-780a30f87b39)

![WebApp](https://github.com/user-attachments/assets/a7f7f2b5-033f-4542-b126-047381974400)
![Transcription](https://github.com/user-attachments/assets/0d5a575d-4c87-4ee1-a3a7-c7c2d8e2f1c7)

## Key Features

- **Audio Transcription**
  - Upload WAV/MP3/FLAC files
  - Real-time transcription with word-level confidence scores
  - Supports long audio files (chunked processing)
  - Mistral-8x7B (via Together.ai) LLM
- **Text-to-Speech Playback**
  - DeepGram TTS integration
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
  - [LLM Mistral](https://www.together.ai/models/mistral-beb7b)

## Setup

### Prerequisites

- Python 3.8+
- MongoDB Atlas or local MongoDB instance
- Deepgram API key
- Together/Mistal API key
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
      TOGETHER_API_KEY=your_together_key_here

  OR Update them in the Dockerfile

      ENV MONGODB_URI=mongodb_connection_string
      ENV DEEPGRAM_API_KEY=your_deepgram_key_here
      ENV APP_URL=https://<your generated url>.ngrok-free.app
      ENV TOGETHER_API_KEY=your_together_key_here
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
