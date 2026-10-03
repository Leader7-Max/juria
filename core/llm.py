import os
import io
import tempfile
from google import genai
from gtts import gTTS
from core.config import GEMINI_API_KEY, GEMINI_MODEL

# Initialisation du client google-genai
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def generate(prompt_or_messages, *args, model=None, **kwargs):
    """Génère du texte en utilisant le client officiel google-genai."""
    if not client:
        raise RuntimeError("La clé API Gemini n'est pas configurée.")
    
    selected_model = model or GEMINI_MODEL
    
    # Transformation des messages au format texte si on reçoit une liste de dictionnaires
    if isinstance(prompt_or_messages, list):
        prompt_parts = []
        for msg in prompt_or_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt_parts.append(f"{role}: {content}")
        contents = "\n".join(prompt_parts)
    else:
        contents = str(prompt_or_messages)

    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=contents
        )
        return response.text.strip()
    except Exception as e:
        print(f"Erreur lors de la génération avec le SDK google-genai : {e}")
        raise e

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
