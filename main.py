import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from google.oauth2 import service_account
from google.cloud import speech_v1p1beta1 as speech
from google.cloud.speech_v1p1beta1 import AdaptationClient
from google.auth.transport.requests import Request
from google.protobuf import field_mask_pb2
import tempfile
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()

# Configuration
UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac'}
STOP_WORDS = {'a', 'an', 'the', 'and', 'or', 'but', 'to', 'of', 'at', 'in', 'on'}

# Helper Functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_mongo_client():
    connection_string = os.getenv('MONGODB_URI')
    if not connection_string:
        raise ValueError("MONGODB_URI environment variable not set")
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
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        creds_info = get_credentials()
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        speech_client = speech.SpeechClient(credentials=credentials)

        with open(filepath, 'rb') as audio_file:
            content = audio_file.read()
        audio = speech.RecognitionAudio(content=content)

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
            model="latest_long" # Use the latest_long audio model instead of the latest_short audio model
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

        if not transcripts:
            flash("No speech detected")
            return redirect(url_for('index'))

        return render_template('results.html', transcripts=transcripts)
    except Exception as e:
        flash(f'Transcription failed: {str(e)}')
        return redirect(url_for('index'))

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)