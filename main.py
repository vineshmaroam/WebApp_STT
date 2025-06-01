import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
import tempfile
from functools import wraps
import subprocess
import base64
from deepgram import Deepgram # This is the proper LLM for DeepGram Aura but requires a paid subscription
#from deepgram import DeepgramClient, PrerecordedOptions, SpeakOptions
import asyncio
import websockets
from websockets.sync.client import connect
import datetime
import requests
#from gtts import gTTS
import io
from together import Together  # Added this import as placeholder for a free to use LLM in the demo: Together/Mistral


def base64_encode(value):
    return base64.b64encode(value).decode('utf-8')

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()
app.jinja_env.filters['b64encode'] = base64_encode

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()

# Initialize Deepgram
dg_stt_client = Deepgram(os.getenv("DEEPGRAM_API_KEY"))
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"
DEEPGRAM_TTS_API_KEY = os.getenv("DEEPGRAM_API_KEY") 
DEEPGRAM_LLM_WS_URL = "wss:https://api.deepgram.com/v1/"
DEEPGRAM_LLM_URL = "https://api.deepgram.com/v1/"

DEEPGRAM_LLM_MODEL = "aura-asteria-en"  # Paid DeepGram Aura LLM model
# Initialize APIs for Together/Mistral
#TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")  # Add to your .env
#TOGETHER_MODEL = "mistralai/Mixtral-8x7B-Instruct-v0.1"  # Free Together/Mistral model


# Configuration
UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac'}

# Helper Functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    client = MongoClient(os.getenv("MONGODB_URI"))
    return client.speech_app

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
async def process_with_deepgram_llm(text, voice_model=DEEPGRAM_LLM_MODEL):
    """Process text with Deepgram LLM and get TTS response via WebSocket"""
    try:
        # Connect to Deepgram's LLM+TTS WebSocket
        with connect(
            f"{DEEPGRAM_LLM_WS_URL}&encoding=linear16&sample_rate=16000",
            additional_headers={"Authorization": f"Token {DEEPGRAM_TTS_API_KEY}"}
        ) as websocket:
            
            # Send the text to Deepgram LLM
            websocket.send(json.dumps({
                "type": "Speak",
                "text": text,
                "model": voice_model
            }))
            
            # Get the audio response
            audio_data = bytearray()
            while True:
                message = websocket.recv()
                if isinstance(message, bytes):
                    audio_data.extend(message)
                elif isinstance(message, str):
                    data = json.loads(message)
                    if data.get("type") == "Finished":
                        break
            
            return base64.b64encode(audio_data).decode('utf-8')
            
    except Exception as e:
        print(f"Deepgram LLM WebSocket error: {str(e)}")
        return None

# Add this new function to generate TTS audio
# def generate_tts(text, voice="aura-asteria-en"):
#     try:
#         print(f"Generating TTS for: {text[:50]}...")  # Debug
#         headers = {
#             "Authorization": f"Token {DEEPGRAM_TTS_API_KEY}",
#             "Content-Type": "application/json"
#         }
        
#         payload = {
#             "text": text,
#             "model": voice,  # Default voice
#             "encoding": "linear16",
#             "container": "wav"
#         }
#         print(f"Sending TTS request to Deepgram with payload: {payload}")  # Debug
#         response = requests.post(
#             DEEPGRAM_TTS_URL,
#             headers=headers,
#             json=payload
#         )
#         print(f"TTS response status: {response.status_code}")  # Debug
#         if response.status_code == 200:
#             print("TTS generation successful")
#             return base64.b64encode(response.content).decode('utf-8')
#         else:
#             print(f"TTS API Error: {response.status_code} - {response.text}")
#             return None
#     except Exception as e:
#         print(f"TTS Generation Error: {str(e)}")
#         return None      

def generate_tts(text, voice, lang='en'):
    """Generate TTS audio using Google's TTS API"""
    try:
        print(f"Generating TTS for: {text[:100]}... with voice {voice} (lang: {lang})")
        
        headers = {
            "Authorization": f"Token {DEEPGRAM_TTS_API_KEY}",
            "Content-Type": "application/json"
        }     
        # Minimal required payload
        payload = {"text": text}
        
        # Voice model as query parameter
        params = {"model": voice}

        print(f"Sending to Deepgram TTS: {payload} with params: {params}")
        # Make request with both JSON payload and query parameters
        response = requests.post(
            DEEPGRAM_TTS_URL,
            headers=headers,
            json=payload,
            params=params,
            timeout=10
        )
        if response.status_code == 200:
            return base64.b64encode(response.content).decode('utf-8')
        else:
            print(f"Deepgram Error: {response.status_code} - {response.text}")
            return None
        
        
    except Exception as e:
        print(f"TTS Generation Error: {str(e)}")
        return None

def estimate_audio_duration(filepath):
    """Estimate audio duration using ffprobe"""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries',
            'format=duration', '-of',
            'default=noprint_wrappers=1:nokey=1', filepath
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return float(result.stdout)
    except:
        return 0  # Fallback if ffprobe fails
    
# Add this new function to generate TTS audio
# @app.route('/generate_tts', methods=['POST'])
# @login_required
# def handle_tts_generation():
#     data = request.json
#     audio_content = generate_tts(data['text'], data['voice'])
#     return jsonify({
#         'audio_content': audio_content,
#         'index': data['index']
#     })
@app.route('/generate_tts', methods=['POST'])
@login_required
def handle_tts_generation():
    
    try:
        data = request.get_json()
        print("Raw TTS request data:", data)  # Debug incoming request


        # Validate required fields
        if not data or 'text' not in data:
            print("Missing text parameter")  # Debug
            return jsonify({'error': 'Missing text parameter'}), 400
        
        # Get voice with default if not provided
        voice = data.get('voice', 'aura-asteria-en')
        print(f"Generating TTS for text (length: {len(data['text'])}) with voice: {voice}")  # Debug

        # Generate TTS with Deepgra
        audio_content = generate_tts(data['text'], voice)
        
        if not audio_content:
            print("TTS generation failed")  # Debug
            return jsonify({'error': 'Failed to generate TTS'}), 500
            
        return jsonify({
            'audio_content': audio_content,
            'index': data.get('index')
        })
       
        
    except Exception as e:
        print(f"TTS Generation Error: {str(e)}")
        return jsonify({'error': str(e)}), 500
# Auth Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()

        if db.users.find_one({"username": username}):
            flash("Username already exists")
            return redirect(url_for('register'))

        user_id = db.users.insert_one({
            "username": username,
            "password": generate_password_hash(password)
        }).inserted_id

        flash("Registration successful! Please login")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.users.find_one({"username": username})

        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = username
            return redirect(url_for('index'))
        flash("Invalid username or password")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# App Routes
@app.route('/')
@login_required
def index():
    db = get_db()
    phrases = list(db.phrases.find({"user_id": session['user_id']}, {'_id': 0}))
    return render_template('index.html', phrases=phrases)

@app.route('/add_phrase', methods=['POST'])
@login_required
def add_phrase():
    phrase = request.form.get('phrase', '').strip()
    boost = request.form.get('boost', '10').strip()

    if not phrase:
        flash("Phrase cannot be empty")
        return redirect(url_for('index'))

    try:
        boost_value = float(boost)
        db = get_db()

        if not db.phrases.find_one({"user_id": session['user_id'], "phrase": phrase}):
            db.phrases.insert_one({
                "user_id": session['user_id'],
                "phrase": phrase,
                "boost": boost_value
            })
            flash("Phrase added successfully!")
        else:
            flash("Phrase already exists")

    except ValueError:
        flash("Boost must be a number")
    except Exception as e:
        flash(f"Error: {str(e)}")

    return redirect(url_for('index'))

@app.route('/delete_phrase/<phrase>', methods=['POST'])
@login_required
def delete_phrase(phrase):
    try:
        db = get_db()
        db.phrases.delete_one({
            "user_id": session['user_id'],
            "phrase": phrase
        })
        flash("Phrase deleted successfully!")
    except Exception as e:
        flash(f"Error deleting phrase: {str(e)}")

    return redirect(url_for('index'))


@app.route('/transcribe', methods=['POST'])
@login_required
def transcribe():
    # ===== 1. INITIAL SETUP =====
    print("\n" + "="*40)
    print("=== TRANSCRIPTION PIPELINE STARTED ===")
    print("="*40 + "\n")
    
    # ===== 2. FILE VALIDATION =====
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('index'))

    file = request.files['file']
    if not file or file.filename == '':
        flash('No file selected')
        return redirect(url_for('index'))
    
    if not allowed_file(file.filename):
        flash(f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}')
        return redirect(url_for('index'))

    # ===== 3. AUDIO PROCESSING =====
    try:
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(file.filename)[1]) as tmp:
            # ---- 3.1 Secure File Saving ----
            try:
                file.save(tmp.name)
                print(f"[1/5] Audio saved to: {tmp.name}")
                print(f"File Info: Size={os.path.getsize(tmp.name)} bytes, Type={file.mimetype}")
                
                # Verify audio integrity
                duration = estimate_audio_duration(tmp.name)
                if duration <= 0:
                    raise ValueError("Invalid audio duration (0s)")
                print(f"Audio validated: Duration={duration:.2f}s")
                
            except Exception as e:
                flash('Error processing audio file')
                print(f"🚨 File Error: {str(e)}")
                return redirect(url_for('index'))

            # ---- 3.2 Deepgram STT ----
            print("\n[2/5] Starting Deepgram STT...")
            try:
                with open(tmp.name, 'rb') as audio_file:
                    stt_response = dg_stt_client.transcription.sync_prerecorded(
                        {'buffer': audio_file, 'mimetype': file.mimetype},
                        options={
                            "punctuate": True,
                            "utterances": True,
                            "smart_format": True,
                            "diarize": False
                        }
                    )
                
                if not stt_response.get('results'):
                    raise ValueError("No speech content detected")
                    
                original_text = stt_response['results']['channels'][0]['alternatives'][0]['transcript']
                confidence = stt_response['results']['channels'][0]['alternatives'][0]['confidence']
                print(f"STT Success: Confidence={confidence:.0%}")
                print(f"Raw Transcript: {original_text}")

            except Exception as e:
                flash('Speech recognition failed')
                print(f"🚨 STT Error: {str(e)}")
                return redirect(url_for('index'))

            # ---- 3.3 Together.ai LLM ----
            print("\n[3/5] Enhancing with Mixtral LLM...")
            try:
                together_client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
                llm_response = together_client.chat.completions.create(
                    model="mistralai/Mixtral-8x7B-Instruct-v0.1",
                    messages=[
                        {
                            "role": "system", 
                            "content": "Improve this transcript while preserving meaning. Correct grammar and enhance clarity:"
                        },
                        {"role": "user", "content": original_text}
                    ],
                    temperature=0.3,
                    max_tokens=500
                )
                processed_text = llm_response.choices[0].message.content
                
                # Compare original vs enhanced
                print("\nText Comparison:")
                print(f"Original: {original_text}")
                print(f"Enhanced: {processed_text}")
                print(f"Character Delta: {len(processed_text) - len(original_text)}")

            except Exception as e:
                print(f"⚠️ LLM Error: {str(e)} - Using original transcript")
                processed_text = original_text

            # ---- 3.4 Deepgram TTS ----
            print("\n[4/5] Generating TTS with Deepgram Aura...")
            try:
                headers = {
                    "Authorization": f"Token {DEEPGRAM_TTS_API_KEY}",
                    "Content-Type": "application/json"
                }
                tts_response = requests.post(
                    f"{DEEPGRAM_TTS_URL}?model={DEEPGRAM_LLM_MODEL}",
                    headers=headers,
                    json={"text": processed_text},
                    timeout=10
                )
                
                if tts_response.status_code == 200:
                    audio_content = base64.b64encode(tts_response.content).decode('utf-8')
                    print("TTS Success: Audio generated")
                else:
                    raise Exception(f"HTTP {tts_response.status_code}: {tts_response.text}")

            except Exception as e:
                print(f"⚠️ TTS Error: {str(e)}")
                audio_content = None

            # ===== 4. RESULTS PREPARATION =====
            print("\n[5/5] Finalizing results...")
            transcript_data = {
                'transcript': processed_text,
                'original': original_text,
                'confidence': f"{confidence:.0%}",
                'words': stt_response['results']['channels'][0]['alternatives'][0].get('words', []),
                'audio_content': audio_content,
                'processing_stats': {
                    'stt_time': duration,
                    'llm_changes': processed_text != original_text
                }
            }

            print("\n" + "="*40)
            print("=== PIPELINE COMPLETED SUCCESSFULLY ===")
            print("="*40 + "\n")
            
            return render_template('results.html',
                transcripts=[transcript_data],
                llm_processed=transcript_data['processing_stats']['llm_changes'],
                llm_model="Mixtral-8x7B",
                tts_model=DEEPGRAM_LLM_MODEL,
                original_text=original_text
            )

    except Exception as e:
        print(f"\n🚨🚨 CRITICAL ERROR: {str(e)}")
        flash('System error during processing')
        return redirect(url_for('index'))
    
def process_audio_with_deepgram(filepath):
    """Process audio files with Deepgram"""
    # Check file duration
    duration = estimate_audio_duration(filepath)
    
    if duration > 60:  # More than 1 minute
        return process_long_audio(filepath)
    else:
        return process_short_audio(filepath)

def process_short_audio(filepath):
    """Process short audio files (<1 min) synchronously"""
    try:
        print(f"Processing short audio: {filepath}")  # Debug
        with open(filepath, 'rb') as audio:
            source = {'buffer': audio, 'mimetype': 'audio/' + filepath.split('.')[-1]}
        
            db = get_db()
            user_phrases = list(db.phrases.find({"user_id": session['user_id']}, {'_id': 0}))
            phrases = [p["phrase"] for p in user_phrases]
        
            options = {
                "model": "nova-2",
                "language": "en-US",
                "punctuate": True,
                "utterances": True,
                "diarize": False,
                "smart_format": True,
                "custom_keywords": phrases if phrases else None
            }
            print(f"Sending to Deepgram with options: {options}")  # Debug
            
            # Make the API call and get response
            response = dg_stt_client.transcription.sync_prerecorded(source, options)
            print(f"Received Deepgram response: {response}")  # Debug
            
            if 'results' not in response:
                flash("No speech detected")
                return redirect(url_for('index'))
            
            return process_deepgram_response(response)
    
    except Exception as e:
        print(f"Error in process_short_audio: {str(e)}")  # Debug
        flash(f"Transcription failed: {str(e)}")
        return redirect(url_for('index'))
    
def process_deepgram_response(response):
    transcripts = []
    for channel in response['results']['channels']:
        for alternative in channel['alternatives']:
            if 'transcript' in alternative:
                transcript_text = alternative['transcript']
                print(f"\n[LLM INPUT] Sending to LLM: {transcript_text}\n")  # Debug log
                
                # Generate TTS with default voice
                audio_content = generate_tts(transcript_text, 'en')  # Explicit default voice
                
                transcript_item = {
                    'transcript': transcript_text,
                    'original': transcript_text,
                    'confidence': f"{alternative['confidence']:.0%}",
                    'words': alternative.get('words', []),
                    'audio_content': audio_content,
                    'audio_format': 'wav'
                }
                transcripts.append(transcript_item)
                return transcripts
    
    
def process_long_audio(filepath):
    """Process long audio files (>1 min) asynchronously"""
    try:
        # For demo purposes, we'll just use the local file path
        # In production, you'd upload to cloud storage first
        file_url = f"file://{os.path.abspath(filepath)}"
        
        db = get_db()
        user_phrases = list(db.phrases.find({"user_id": session['user_id']}, {'_id': 0}))
        phrases = [p["phrase"] for p in user_phrases]
        
        options = {
            "model": "nova-2",
            "language": "en-US",
            "punctuate": True,
            "utterances": True,
            "diarize": False,
            "smart_format": True,
            "custom_keywords": phrases if phrases else None,
            "callback": f"{os.getenv('APP_URL')}/callback"  # Your callback endpoint
        }

        # Start async transcription
        response = dg_stt_client.transcription.prerecorded(
            {'url': file_url},
            options
        )
        
        # Store the request ID to track later
        request_id = response.get('request_id')
        if not request_id:
            flash("Failed to start transcription")
            return redirect(url_for('index'))
            
        # Store the request ID in the database to track later
        db.transcription_requests.insert_one({
            'user_id': session['user_id'],
            'request_id': request_id,
            'status': 'processing',
            'created_at': datetime.datetime.now()
        })
        
        flash("Your audio is being processed. We'll notify you when it's ready.")
        return redirect(url_for('index'))
        
    except Exception as e:
        flash(f"Transcription failed: {str(e)}")
        return redirect(url_for('index'))

def process_deepgram_response(response):
    """Process Deepgram response"""
    print("Processing Deepgram response...")  # Debug
    transcripts = []
    
    if 'results' not in response:
        flash("No speech detected in audio")
        return redirect(url_for('index'))
    
    for channel in response['results']['channels']:
        for alternative in channel['alternatives']:
            if 'transcript' in alternative:
                 transcript_text = alternative['transcript']
                 print(f"Processing transcript: {transcript_text[:100]}...")  # Debug
                 
                 # Generate TTS audio
                 audio_content = generate_tts(transcript_text)
                 
                 if audio_content is None:
                    print("Warning: TTS generation failed for transcript")
                 # Build transcript item
                 transcript_item = {
                    'transcript': transcript_text,
                    'original': transcript_text,
                    'confidence': f"{alternative['confidence']:.0%}",
                    'words': [{
                        'word': word['word'],
                        'confidence': word['confidence']
                    } for word in alternative.get('words', [])],
                    'audio_content': audio_content,  # This can be None if TTS failed
                    'audio_format': 'wav'
                }
                
                 print(f"Transcript item: {transcript_item.keys()}")  # Debug
                 transcripts.append(transcript_item)

    if not transcripts:
        flash("No speech detected")
        return redirect(url_for('index'))
    
    return render_template('results.html', transcripts=transcripts)

@app.route('/upload_audio_blob', methods=['POST'])
@login_required
def upload_audio_blob():
    if 'audio_data' not in request.files:
        return jsonify({'error': 'No audio file received'}), 400

    audio_file = request.files['audio_data']
    if audio_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    try:
        # Save the audio blob to a temporary file
        filename = secure_filename(f"recording_{session['user_id']}.wav")
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        audio_file.save(filepath)

        with open(filepath, 'rb') as audio:
            source = {'buffer': audio, 'mimetype': 'audio/wav'}
            
            # Get user phrases
            db = get_db()
            user_phrases = list(db.phrases.find({"user_id": session['user_id']}, {'_id': 0}))
            phrases = [p["phrase"] for p in user_phrases]
            
            options = {
                "model": "nova-2",
                "language": "en-US",
                "punctuate": True,
                "utterances": True,
                "smart_format": True,
                "custom_keywords": phrases if phrases else None
            }

            response = dg_stt_client.transcription.sync_prerecorded(source, options)
            
            if 'results' not in response:
                return jsonify({'error': 'No speech detected'}), 400
                
            transcripts = []
            for channel in response['results']['channels']:
                for alternative in channel['alternatives']:
                    if 'transcript' in alternative:
                         # FIX: Use the correct voice parameter from frontend
                        voice = request.form.get('voice', 'aura-asteria-en')
                        audio_content = generate_tts(alternative['transcript'], voice)
                        transcripts.append({
                            'transcript': alternative['transcript'],
                            'confidence': f"{alternative['confidence']:.0%}",
                            'audio_content': audio_content  # Will be None if TTS fails
                        })

            return jsonify({'transcripts': transcripts})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/callback', methods=['POST'])
def deepgram_callback():
    """Handle Deepgram callback with results"""
    try:
        data = request.json
        request_id = data.get('request_id')
        
        if not request_id:
            return jsonify({'error': 'Missing request_id'}), 400
            
        db = get_db()
        request_record = db.transcription_requests.find_one({'request_id': request_id})
        
        if not request_record:
            return jsonify({'error': 'Unknown request'}), 404
            
        # Update the request status
        db.transcription_requests.update_one(
            {'request_id': request_id},
            {'$set': {'status': 'completed', 'results': data}}
        )
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
# Uncomment this new route for LLM conversation with Deepgram Aura and comment the other /chat route there after 
# Or just the commented out part in the route for Together/Mistral and uncomment the part for DeepGram
# @app.route('/chat', methods=['POST'])
# @login_required
# def chat_with_llm():
#     """
#     Endpoint to chat with Deepgram's LLM (Aura)
#     Expects JSON with:
#     - message: User's text message
#     - conversation_id: Optional existing conversation ID
#     - voice: Optional voice model override
#     """
#     try:
#         data = request.json
#         message = data.get('message')
#         voice = data.get('voice', DEEPGRAM_LLM_MODEL)
        
#         if not message:
#             return jsonify({'error': 'Message is required'}), 400
#         # Prepare the LLM request
#         headers = {
#             "Authorization": f"Token {DEEPGRAM_TTS_API_KEY}",
#             "Content-Type": "application/json"
#         }    
#         # Prepare the payload according to Deepgram's LLM API requirements
#         payload = {
#             "model": data.get('voice', DEEPGRAM_LLM_MODEL),  # Use selected voice or default
#             "query": message,
#             "conversation_id": data.get('conversation_id')
#         }
        
#         # Include conversation_id if provided
#         if 'conversation_id' in data and data['conversation_id']:
#             payload["conversation_id"] = data['conversation_id']
        
#         headers = {
#             "Authorization": f"Token {DEEPGRAM_TTS_API_KEY}",
#             "Content-Type": "application/json",
#             "Accept": "application/json"
#         }
        
       
#         # Make the LLM request
#         response = requests.post(
#             DEEPGRAM_LLM_URL,
#             headers=headers,
#             json=payload,
#             timeout=30
#         )
#         if response.status_code != 200:
#             print(f"Deepgram LLM API Error: {response.status_code} - {response.text}")  # Debug
#             return jsonify({
#                 'error': f"LLM API Error: {response.status_code}",
#                 'details': response.text
#             }), response.status_code
            
#         response_data = response.json()
     

#         # Generate TTS audio for the response
#         llm_response = response_data.get('response', '')

#         # Generate TTS audio using the same voice
#         tts_response = requests.post(
#             DEEPGRAM_TTS_URL,
#             headers=headers,
#             json={
#                 "text": llm_response,
#                 "model": voice,
#                 "encoding": "linear16",
#                 "container": "wav"
#             }
#         )


#         audio_content = None
#         if tts_response.status_code == 200:
#             audio_content = base64.b64encode(tts_response.content).decode('utf-8')
#         return jsonify({
#             'response': llm_response,
#             'conversation_id': response_data.get('conversation_id'),
#             'audio_content': audio_content,
#             'model': voice
#         })
        
#     except Exception as e:
#         print(f"Chat error: {str(e)}")  # Debug
#         return jsonify({'error': str(e)}), 500

# # Add this new route for the chat interface
# # Modified /chat endpoint with Together/Mistral LLM fallback
@app.route('/chat', methods=['POST'])
@login_required
def chat_with_llm():
    """
    Endpoint to chat with LLM (using Together.ai free tier now, Deepgram commented for future)
    """
    try:
        data = request.json
        message = data.get('message')
        voice = data.get('voice', 'aura-asteria-en')  # Keep voice selection for TTS
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400

        # --- Together.ai Implementation (Free Tier) ---
        # together_client = Together(api_key=TOGETHER_API_KEY)
        # llm_response = together_client.chat.completions.create(
        #     model=TOGETHER_MODEL,
        #     messages=[{"role": "user", "content": message}]
        # ).choices[0].message.content

        # --- Deepgram Aura Implementation (Commented for Future Paid Use) ---
        
        # Prepare the LLM request
        headers = {
            "Authorization": f"Token {DEEPGRAM_TTS_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": voice,
            "query": message,
            "conversation_id": data.get('conversation_id')
        }
        
        response = requests.post(
            DEEPGRAM_LLM_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({"error": response.json()}), response.status_code
            
        response_data = response.json()
        llm_response = response_data.get('response', '')
        

        # Generate TTS audio (using same voice selection)
        audio_content = generate_tts(llm_response, voice)
        
        return jsonify({
            'response': llm_response,
            'conversation_id': data.get('conversation_id', ''),  # Empty for Together.ai
            'audio_content': audio_content,
            'model': voice
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
