# If you see "Import 'face_recognition' could not be resolved", install it with:
# pip install face_recognition
from flask import Flask, request, render_template, redirect, url_for, session, send_from_directory, jsonify
import os
import face_recognition
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# In-memory event/password store (replace with DB in production)
EVENTS = {}  # event_id: password

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

ACTIVE_USERS = set()  # (event_id, guest identifier)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_event_folder(event_id):
    return os.path.join(UPLOAD_FOLDER, event_id)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error="Invalid credentials")
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin', methods=['GET'])
@admin_required
def admin_dashboard():
    # Count total photos (exclude .enc files)
    total_photos = 0
    for event_id in EVENTS:
        event_folder = get_event_folder(event_id)
        if os.path.exists(event_folder):
            for fname in os.listdir(event_folder):
                if fname.lower().split('.')[-1] in ALLOWED_EXTENSIONS:
                    total_photos += 1
    active_users = len(ACTIVE_USERS)
    return render_template('admin_dashboard.html', events=EVENTS, total_photos=total_photos, active_users=active_users)

@app.route('/admin/create_event', methods=['GET', 'POST'])
@admin_required
def create_event():
    if request.method == 'POST':
        event_id = request.form['event_id']
        password = request.form['password']
        if not event_id or not password:
            return render_template('create_event.html', error="Event ID and password required")
        if event_id in EVENTS:
            return render_template('create_event.html', error="Event ID already exists")
        EVENTS[event_id] = password
        return redirect(url_for('admin_dashboard'))
    return render_template('create_event.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        event_id = request.form['event_id']
        password = request.form['password']
        files = request.files.getlist('image')
        if not (event_id and password and files and all(f and allowed_file(f.filename) for f in files)):
            return "Invalid input", 400
        # Require event to exist and password to match
        if event_id not in EVENTS:
            return "Event does not exist. Contact admin.", 403
        if EVENTS[event_id] != password:
            return "Incorrect password for this event", 403
        event_folder = get_event_folder(event_id)
        os.makedirs(event_folder, exist_ok=True)
        for file in files:
            filename = secure_filename(file.filename)
            filepath = os.path.join(event_folder, filename)
            file.save(filepath)
            # Save face encoding
            image = face_recognition.load_image_file(filepath)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                with open(os.path.join(event_folder, filename + '.enc'), 'wb') as f:
                    import pickle
                    pickle.dump(encodings[0], f)
        return "Uploaded", 200
    return render_template('upload.html')

@app.route('/guest', methods=['GET', 'POST'])
def guest():
    if request.method == 'POST':
        event_id = request.form['event_id']
        password = request.form['password']
        file = request.files.get('face')
        if not (event_id and password and file and allowed_file(file.filename)):
            return "Invalid input", 400
        # Check event/password
        if EVENTS.get(event_id) != password:
            return "Invalid event ID or password", 403
        # Load guest face encoding
        guest_image = face_recognition.load_image_file(file)
        guest_encodings = face_recognition.face_encodings(guest_image)
        if not guest_encodings:
            return "No face found", 400
        guest_encoding = guest_encodings[0]
        # Compare with stored encodings
        event_folder = get_event_folder(event_id)
        matched_images = []
        for fname in os.listdir(event_folder):
            if fname.endswith('.enc'):
                with open(os.path.join(event_folder, fname), 'rb') as f:
                    import pickle
                    known_encoding = pickle.load(f)
                results = face_recognition.compare_faces([known_encoding], guest_encoding)
                if results[0]:
                    img_name = fname[:-4]
                    matched_images.append(url_for('uploaded_file', event_id=event_id, filename=img_name))
        # Track active user (event_id + guest face encoding hash)
        ACTIVE_USERS.add((event_id, str(hash(guest_encoding.tobytes()))))
        return render_template('gallery.html', images=matched_images)
    return render_template('guest.html')

@app.route('/uploads/<event_id>/<filename>')
def uploaded_file(event_id, filename):
    return send_from_directory(get_event_folder(event_id), filename)

@app.route('/admin/delete_event/<event_id>', methods=['POST'])
@admin_required
def delete_event(event_id):
    # Remove from EVENTS
    if event_id in EVENTS:
        EVENTS.pop(event_id)
        # Remove event folder and files
        event_folder = get_event_folder(event_id)
        import shutil
        if os.path.exists(event_folder):
            shutil.rmtree(event_folder)
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
