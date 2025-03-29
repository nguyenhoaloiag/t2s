from flask import Flask, request, jsonify, send_from_directory
import re
from gtts import gTTS  # Replace with Piper if needed
import os
import uuid

app = Flask(__name__)

# Dictionary for common abbreviation replacements
ABBREVIATIONS = {
    "km": "kilometer",
    "w": "watt",
    "min": "minute",
    "sec": "second",
    "hr": "hour",
    # Add more abbreviations as needed
}

# Function to preprocess text
def preprocess_text(text):
    text = re.sub(r"[\n\?~]", ",", text)
    for abbr, full in ABBREVIATIONS.items():
        text = re.sub(rf"\b{abbr}\b", full, text, flags=re.IGNORECASE)
    return text

# Serve index.html
@app.route("/")
def serve_index():
    return send_from_directory("static", "index.html")

# Endpoint to serve audio files
@app.route("/audio/<filename>")
def serve_audio(filename):
    return send_from_directory("static/audio", filename)

# Convert text to audio and return full download URL
@app.route("/convert", methods=["POST"])
def convert_text_to_audio():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid input. Please provide text and language."}), 400
        
        text = data.get("text", "").strip()
        lang = data.get("lang", "en").strip()

        if not text:
            return jsonify({"error": "Text is required."}), 400
        if not lang:
            return jsonify({"error": "Language is required."}), 400

        # Preprocess and convert
        processed_text = preprocess_text(text)
        tts = gTTS(text=processed_text, lang=lang)

        # Unique filename
        filename = f"{uuid.uuid4().hex}.mp3"
        output_path = os.path.join("static", "audio", filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        tts.save(output_path)

        # Return full URL (absolute)
        base_url = request.host_url.rstrip("/")  # e.g. http://localhost:5000
        full_url = f"{base_url}/audio/{filename}"
        return jsonify({"audio_url": full_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    os.makedirs("static/audio", exist_ok=True)
    app.run(debug=True, host="0.0.0.0", port=5000)
