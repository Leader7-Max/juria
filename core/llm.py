import os
import io
import tempfile

try:
    import google.generativeai as genai
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

from core.config import GEMINI_MODEL

# Configuration sécurisée de l'API Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if api_key and API_AVAILABLE:
    genai.configure(api_key=api_key)

def transcribe(audio_bytes: bytes) -> str:
    """Transcrit un enregistrement audio en texte via Gemini (avec sécurité si l'API n'est pas prête)."""
    if not api_key or not API_AVAILABLE:
        raise RuntimeError("La clé API Gemini n'est pas configurée ou le module n'est pas disponible.")
    
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
    if not GTTS_AVAILABLE:
        return b""
    tts_obj = gTTS(text=text, lang=lang, slow=False)
    fp = io.BytesIO()
    tts_obj.write_to_fp(fp)
    fp.seek(0)
    return fp.read()
