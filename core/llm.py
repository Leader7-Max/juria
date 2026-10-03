"""Module d'interaction avec les modèles Gemini."""
import streamlit as st
from google import genai
from core.config import GEMINI_MODEL, EMBED_MODEL, secret

def get_gemini_client():
    """Initialise et retourne le client Google GenAI."""
    api_key = secret("GEMINI_API_KEY")
    if not api_key:
        st.error("La clé API Gemini (GEMINI_API_KEY) est introuvable dans les secrets ou l'environnement.")
    return genai.Client(api_key=api_key)

def generate_text(prompt: str, system_instruction: str = None) -> str:
    """Génère du texte via le modèle Gemini configuré."""
    client = get_gemini_client()
    config = {}
    if system_instruction:
        config["system_instruction"] = system_instruction
        
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=config if config else None
    )
    return response.text

def get_embedding(text: str) -> list[float]:
    """Génère les embeddings (vecteurs) d'un texte pour le RAG."""
    client = get_gemini_client()
    response = client.models.embed_content(
        model=EMBED_MODEL,
        contents=text
    )
    # Retourne la liste des valeurs de l'embedding
    return response.embedding.values
