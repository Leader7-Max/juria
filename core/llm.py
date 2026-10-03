import os
import io
import tempfile
import time
from google import genai
from gtts import gTTS
from core.config import GEMINI_API_KEY, GEMINI_MODEL

# Initialisation du client google-genai
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def generate(prompt_or_messages, system_prompt=None, json_mode=False, web=False, model=None, **kwargs):
    """
    Génère du texte via google-genai et renvoie TOUJOURS un tuple (texte, metadonnees/sources)
    pour éviter toute erreur de déballage (unpacking) dans le pipeline.
    """
    if not client:
        raise RuntimeError("La clé API Gemini n'est pas configurée.")
    
    selected_model = model or GEMINI_MODEL
    
    # Construction du contenu des messages
    contents = []
    if system_prompt:
        contents.append(f"INSTRUCTIONS SYSTÈME :\n{system_prompt}\n")

    if isinstance(prompt_or_messages, list):
        for msg in prompt_or_messages:
            if hasattr(msg, "role") and hasattr(msg, "parts"):  # Objet GenAI Part (ex: bytes upload)
                contents.append(msg)
            elif isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                contents.append(f"{role}: {content}")
            else:
                contents.append(str(msg))
    else:
        contents.append(str(prompt_or_messages))

    # Configuration de la requête (JSON mode si demandé)
    config = {}
    if json_mode:
        config["response_mime_type"] = "application/json"

    # Tentatives multiples en cas de surcharge temporaire (erreur 503)
    max_retries = 3
    response = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=selected_model,
                contents=contents,
                config=config if config else None
            )
            break
        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))  # Attente exponentielle (2s, 4s...)
                continue
            if attempt == max_retries - 1:
                print(f"Erreur persistante après {max_retries} tentatives : {e}")
            raise e

    text_result = response.text.strip() if response and response.text else ""
    
    # Le pipeline s'attend à recevoir un tuple de 2 éléments : (texte, sources_web)
    web_sources = []
    return text_result, web_sources

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
