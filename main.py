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
from deepgram import Deepgram
import datetime
import requests
from gtts import gTTS
import io

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

def generate_tts(text, lang='en'):
    """Generate TTS audio using Google's TTS API"""
    try:
        print(f"Generating Google TTS for: {text[:100]}...")
        
        # Create in-memory file
        mp3_fp = io.BytesIO()
        
        # Generate TTS
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        
        # Convert to base64 for embedding in HTML
        audio_content = base64.b64encode(mp3_fp.read()).decode('utf-8')
        print("Google TTS generation successful")
        return audio_content
        
    except Exception as e:
        print(f"Google TTS Generation Error: {str(e)}")
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
    data = request.json
    # Map Deepgram voices to Google TTS languages
    voice_map = {
        'aura-asteria-en': 'en',
        'aura-luna-en': 'en',
        'aura-stella-en': 'en',
        'aura-orion-en': 'en',
        'aura-arcas-en': 'en'
    }
    lang = voice_map.get(data['voice'], 'en')
    audio_content = generate_tts(data['text'], lang)
    return jsonify({
        'audio_content': audio_content,
        'index': data['index']
    })
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
    print("Transcribe endpoint hit")  # Debug
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('index'))

    file = request.files['file']
    print(f"File received: {file.filename}")  # Debug

    if file.filename == '' or not allowed_file(file.filename):
        flash('Invalid file')
        return redirect(url_for('index'))

    try:
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(file.filename)[1]) as tmp:
            print(f"Saving to temp file: {tmp.name}")  # Debug
            file.save(tmp.name)
            return process_audio_with_deepgram(tmp.name)

    except Exception as e:
        print(f"Transcription failed with error: {str(e)}")  # Debug
        flash(f'Transcription failed: {str(e)}')
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
                        transcripts.append({
                            'transcript': alternative['transcript'],
                            'confidence': f"{alternative['confidence']:.0%}"
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
