import os
import io
import tempfile
import google.generativeai as genai
from gtts import gTTS
from core.config import GEMINI_API_KEY, GEMINI_MODEL

# Initialisation indispensable de l'API Gemini avec la clé récupérée
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    raise RuntimeError("La clé API Gemini n'est pas configurée dans les secrets ou l'environnement.")

def transcribe(audio_bytes: bytes) -> str:
    """Transcrit un enregistrement audio en texte via Gemini."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        f.write(audio_bytes)
        temp_name = f.name
    try:
        audio_file = genai.upload_file(temp_name)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content([
            audio_file, 
            "Transcris cet enregistrement audio mot à mot en français, fidèlement, sans ajouter de commentaires ni de mise en forme superflue."
        ])
        return response.text.strip()
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)

def tts(text: str, lang: str = "fr") -> bytes:
    """Génère un fichier audio MP3 à partir d'un texte (synthèse vocale)."""
    tts_obj = gTTS(text=text, lang=lang, slow=False)
    fp = io.BytesIO()
    tts_obj.write_to_fp(fp)
    fp.seek(0)
    return fp.read()
