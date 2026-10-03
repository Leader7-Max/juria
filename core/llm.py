import os
import io
import tempfile
from google import genai
from gtts import gTTS
from core.config import GEMINI_API_KEY, GEMINI_MODEL

# Initialisation du client google-genai
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def transcribe(audio_bytes: bytes) -> str:
    """Transcrit un enregistrement audio en texte via Gemini."""
    if not client:
        raise RuntimeError("La clé API Gemini n'est pas configurée.")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        f.write(audio_bytes)
        temp_name = f.name
    try:
        audio_file = client.files.upload(file=temp_name)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                audio_file, 
                "Transcris cet enregistrement audio mot à mot en français, fidèlement, sans ajouter de commentaires ni de mise en forme superflue."
            ]
        )
        return response.text.strip()
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)

def tts(text: str, lang: str = "fr") -> bytes:
    """Génère un fichier audio MP3 à partir d'un texte."""
    tts_obj = gTTS(text=text, lang=lang, slow=False)
    fp = io.BytesIO()
    tts_obj.write_to_fp(fp)
    fp.seek(0)
    return fp.read()
