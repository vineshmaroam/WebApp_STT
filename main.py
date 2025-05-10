import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from google.oauth2 import service_account
from google.cloud import speech_v1p1beta1 as speech
import google.generativeai as genai
from google.cloud.speech_v1p1beta1 import AdaptationClient
from google.auth.transport.requests import Request
from google.protobuf import field_mask_pb2
import tempfile
from functools import wraps
from flask import jsonify

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()

# Initialize Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
gemini_model = genai.GenerativeModel('gemini-pro')

def enhance_with_gemini(transcript):
    """Use Gemini to correct and format the transcript."""
    prompt = f"""
    Correct any errors in this medical transcript while preserving technical terms:
    {transcript}

    Output ONLY the corrected text with no additional commentary:
    """
    try:
        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini error: {str(e)}")
        return transcript  # Fallback to original

# Configuration
UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac'}
STOP_WORDS = {'a', 'an', 'the', 'and', 'or', 'but', 'to', 'of', 'at', 'in', 'on'}

# Helper Functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# MongoDB Setup
import sys
if 'pymongo' in sys.modules:
    del sys.modules['pymongo']

def get_mongo_client():
    import os
    from importlib import reload
    reload(os)  # Forces reload of environment variables

    connection_string = os.getenv('MONGODB_URI')
    if not connection_string:
        raise ValueError("MONGODB_URI environment variable not set")
    #connection_string = "mongodb+srv://laldeomaroam:1sXgyHuDra1b7rA2@cluster0.svenc6y.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0" 
    return MongoClient(connection_string)

def get_db():
    client = get_mongo_client()
    return client.speech_app

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_phrase_set_id(user_id):
    return f"user-{user_id}-phrases"

# Google Cloud Setup
def get_credentials():
    creds_json = os.getenv('GOOGLE_CREDENTIALS')
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS environment variable not set")
    return json.loads(creds_json)

def get_adaptation_client():
    creds_info = get_credentials()
    creds = service_account.Credentials.from_service_account_info(creds_info)
    if creds.expired:
        creds.refresh(Request())
    return AdaptationClient(credentials=creds)

def initialize_user_phrase_set(user_id):
    try:
        client = get_adaptation_client()
        project_id = os.getenv('PROJECT_ID')
        phrase_set_id = get_user_phrase_set_id(user_id)
        phrase_set_name = f"projects/{project_id}/locations/global/phraseSets/{phrase_set_id}"

        try:
            client.get_phrase_set(name=phrase_set_name)
        except Exception:
            phrase_set = speech.PhraseSet(name=phrase_set_name, phrases=[])
            parent = f"projects/{project_id}/locations/global"
            operation = client.create_phrase_set(
                parent=parent,
                phrase_set_id=phrase_set_id,
                phrase_set=phrase_set
            )
            operation.result(timeout=30)
    except Exception as e:
        print(f"Error initializing PhraseSet: {str(e)}")

def update_user_phrases_in_stt(user_id):
    try:
        db = get_db()
        phrases = list(db.phrases.find({"user_id": user_id}, {'_id': 0}))

        if not phrases:
            return False

        stt_phrases = [{
            "value": p["phrase"],
            "boost": float(p["boost"])
        } for p in phrases]

        client = get_adaptation_client()
        project_id = os.getenv('PROJECT_ID')
        phrase_set_id = get_user_phrase_set_id(user_id)
        phrase_set_name = f"projects/{project_id}/locations/global/phraseSets/{phrase_set_id}"

        phrase_set = speech.PhraseSet(
            name=phrase_set_name,
            phrases=stt_phrases
        )

        update_mask = field_mask_pb2.FieldMask()
        update_mask.paths.append("phrases")

        operation = client.update_phrase_set(
            phrase_set=phrase_set,
            update_mask=update_mask
        )
        operation.result(timeout=30)
        return True
    except Exception as e:
        print(f"PhraseSet update failed: {str(e)}")
        return False

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

        # Initialize phrase set for new user
        initialize_user_phrase_set(str(user_id))

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

            if update_user_phrases_in_stt(session['user_id']):
                flash("Phrase added successfully!")
            else:
                flash("Phrase added but failed to update PhraseSet")
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

        if update_user_phrases_in_stt(session['user_id']):
            flash("Phrase deleted successfully!")
        else:
            flash("Phrase deleted but failed to update PhraseSet")
    except Exception as e:
        flash(f"Error deleting phrase: {str(e)}")

    return redirect(url_for('index'))

@app.route('/transcribe', methods=['POST'])
@login_required
def transcribe():
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        flash('Invalid file')
        return redirect(url_for('index'))

    try:
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(file.filename)[1]) as tmp:
            file.save(tmp.name)
            
            # Check file size (10MB limit for Google STT)
            file_size = os.path.getsize(tmp.name)
            if file_size > 10 * 1024 * 1024:  # 10MB in bytes
                return process_large_audio(tmp.name)
            
            # Process small files normally
            return process_small_audio(tmp.name)

    except Exception as e:
        flash(f'Transcription failed: {str(e)}')
        return redirect(url_for('index'))

def process_small_audio(filepath):
    """Process audio files under 10MB"""
    creds_info = get_credentials()
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    speech_client = speech.SpeechClient(credentials=credentials)

    with open(filepath, 'rb') as audio_file:
        content = audio_file.read()

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="en-US",
        adaptation=speech.SpeechAdaptation(
            phrase_set_references=[
                f"projects/{os.getenv('PROJECT_ID')}/locations/global/phraseSets/{get_user_phrase_set_id(session['user_id'])}"
            ]
        ),
        use_enhanced=True,
        model="latest_long"
    )

    audio = speech.RecognitionAudio(content=content)
    response = speech_client.recognize(config=config, audio=audio)
    return process_response(response)

def process_large_audio(filepath):
    """Process audio files over 10MB using chunking"""
    try:
        # Convert/compress audio first (requires ffmpeg)
        compressed_path = compress_audio(filepath)
        
        # Use async long-running recognition
        operation = long_running_recognize(compressed_path)
        return process_response(operation.result())
        
    finally:
        if os.path.exists(compressed_path):
            os.remove(compressed_path)

def compress_audio(input_path):
    """Convert audio to FLAC with 16kHz sample rate"""
    output_path = f"{input_path}_compressed.flac"
    subprocess.run([
        'ffmpeg', '-i', input_path,
        '-ar', '16000',  # Sample rate
        '-ac', '1',       # Mono channel
        '-y',             # Overwrite
        output_path
    ], check=True)
    return output_path

def long_running_recognize(filepath):
    """Async processing for large files"""
    client = speech.SpeechClient(credentials=get_credentials())
    
    with open(filepath, 'rb') as audio_file:
        content = audio_file.read()

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.FLAC,
        sample_rate_hertz=16000,
        language_code="en-US",
        enable_automatic_punctuation=True,
        adaptation=speech.SpeechAdaptation(
            phrase_set_references=[
                f"projects/{os.getenv('PROJECT_ID')}/locations/global/phraseSets/{get_user_phrase_set_id(session['user_id'])}"
            ]
        ),
        model="latest_long"
    )

    audio = speech.RecognitionAudio(content=content)
    return client.long_running_recognize(config=config, audio=audio)

def process_response(response):
    """Process both sync and async responses"""
    transcripts = []
    for result in response.results:
        if result.alternatives:
            raw_text = result.alternatives[0].transcript
            confidence = result.alternatives[0].confidence
            
            enhanced_text = enhance_with_gemini(raw_text) if confidence < 0.9 else raw_text
            
            transcripts.append({
                'transcript': enhanced_text,
                'original': raw_text,
                'confidence': f"{confidence:.0%}"
            })

    if not transcripts:
        flash("No speech detected")
        return redirect(url_for('index'))
    
    return render_template('results.html', transcripts=transcripts)
@app.route('/submit_corrections', methods=['POST'])
@login_required
def submit_corrections():
    try:
        corrected_texts = request.form.getlist('corrected_text')
        original_texts = request.form.getlist('original_text')
        boost_value = float(request.form.get('boost_value', 10))

        changed_words = set()
        for original, corrected in zip(original_texts, corrected_texts):
            orig_words = set(original.lower().split())
            corrected_words = set(corrected.lower().split())
            changed_words.update(corrected_words - orig_words)

        if not changed_words:
            flash("No word changes detected")
            return redirect(url_for('index'))

        db = get_db()
        added_count = 0

        for word in changed_words:
            if (len(word) > 2 and word.isalpha() and word not in STOP_WORDS):
                if not db.phrases.find_one({"user_id": session['user_id'], "phrase": word}):
                    db.phrases.insert_one({
                        "user_id": session['user_id'],
                        "phrase": word,
                        "boost": boost_value
                    })
                    added_count += 1

        if update_user_phrases_in_stt(session['user_id']):
            flash(f"Added {added_count} new words to your PhraseSet!")
        else:
            flash("Added to database but failed to update PhraseSet")

        return redirect(url_for('index'))
    except Exception as e:
        flash(f"Error submitting corrections: {str(e)}")
        return redirect(url_for('index'))
# Add this new route to handle audio blob uploads
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

        # Process the audio file with Google Speech-to-Text
        creds_info = get_credentials()
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        speech_client = speech.SpeechClient(credentials=credentials)

        with open(filepath, 'rb') as audio_file:
            content = audio_file.read()
        audio = speech.RecognitionAudio(content=content)

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000,  # Changed to match browser recording
            language_code="en-US",
            adaptation=speech.SpeechAdaptation(
                phrase_set_references=[
                    f"projects/{os.getenv('PROJECT_ID')}/locations/global/phraseSets/{get_user_phrase_set_id(session['user_id'])}"
                ]
            ),
            use_enhanced=True,
            model="latest_long"
        )

        response = speech_client.recognize(config=config, audio=audio)
        transcripts = []
        for result in response.results:
            if result.alternatives:
                transcript = result.alternatives[0].transcript
                confidence = result.alternatives[0].confidence
                transcripts.append({
                    'transcript': transcript,
                    'confidence': f"{confidence:.0%}"
                })

        return jsonify({'transcripts': transcripts})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
