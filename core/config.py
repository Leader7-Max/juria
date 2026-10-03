"""Configuration centrale de JURIA (Streamlit + Gemini)."""
import os
from pathlib import Path


def secret(name: str, default: str = "") -> str:
    """Lit une valeur depuis l'environnement, sinon depuis st.secrets."""
    v = os.getenv(name)
    if v:
        return v
    try:
        import streamlit as st
        return str(st.secrets.get(name, default))
    except Exception:
        return default


DATA_DIR = Path(os.getenv("JURIA_DATA_DIR", "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "juria.db"

# Configuration des clés et modèles via les secrets ou variables d'environnement
GEMINI_API_KEY = secret("GEMINI_API_KEY")
GEMINI_MODEL = secret("GEMINI_MODEL", "gemini-1.5-flash")
EMBED_MODEL = secret("GEMINI_EMBED_MODEL", "gemini-embedding-001")
ADMIN_EMAILS = [e.strip().lower() for e in secret("ADMIN_EMAILS").split(",") if e.strip()]
MAX_UPLOAD_MB = 15

# Injection automatique de la clé API pour le SDK Google GenAI si elle est disponible
if GEMINI_API_KEY:
    os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

# Sites officiels PRIVILÉGIÉS pour la recherche web (indications à vérifier, pas une base juridique).
COUNTRIES = {
    "France": ["legifrance.gouv.fr", "service-public.fr", "justice.fr", "conseil-etat.fr",
               "courdecassation.fr", "immigration.interieur.gouv.fr", "defenseurdesdroits.fr"],
    "Suisse": ["fedlex.admin.ch", "sem.admin.ch", "ch.ch", "bger.ch"],
    "Belgique": ["ejustice.just.fgov.be", "belgium.be", "dofi.ibz.be"],
    "Canada": ["laws-lois.justice.gc.ca", "canada.ca", "irb-cisr.gc.ca"],
    "Cameroun": [],
    "Côte d'Ivoire": [],
    "Sénégal": ["jo.gouv.sn"],
    "Gabon": [],
    "République démocratique du Congo": [],
    "Maroc": ["sgg.gov.ma"],
    "Algérie": ["joradp.dz"],
    "Tunisie": ["iort.gov.tn"],
    "Autre": [],
}

DOMAINS = [
    "Immigration / Droit des étrangers",
    "Nationalité et état civil",
    "Famille — mariage, divorce, séparation",
    "Enfants — garde, autorité parentale, pension",
    "Travail",
    "Logement",
    "Administratif / Recours",
    "Autre",
]

STATUSES = ["en_vigueur", "modifié", "abrogé", "archivé"]
LANGS = {"Français": "fr", "English": "en"}
LANG_NAMES = {"fr": "français", "en": "English"}

AI_NOTICE = (
    "Vous échangez avec une intelligence artificielle. Les informations fournies sont destinées "
    "à vous aider à comprendre votre situation juridique et ne remplacent pas nécessairement les "
    "conseils ou la représentation d'un professionnel du droit. Vérifiez les informations "
    "importantes et les délais applicables."
)
SHORT_NOTICE = "🤖 Assistant juridique IA — information juridique, pas un avocat. Vérifiez les délais."
