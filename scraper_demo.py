"""Démo isolée du scraper. Lancer : streamlit run scraper_demo.py  (n'affecte pas app.py)"""
import streamlit as st

from scraper_web import fetch_page

st.set_page_config(page_title="Test scraper JURIA", page_icon="🌐")
st.title("🌐 Test du scraper web")
st.caption("Extrait le texte utile d'une page publique. Le texte n'est PAS une source juridique vérifiée : "
           "contrôlez toujours l'origine et la date avant de l'utiliser.")

url = st.text_input("URL de la page", placeholder="https://www.service-public.fr/...")
only_official = st.checkbox("Limiter aux sites officiels connus (.gouv.fr, .admin.ch, .gc.ca, .belgium.be)", value=False)

if st.button("Extraire le texte", type="primary", use_container_width=True) and url.strip():
    domains = None
    if only_official:
        domains = ["gouv.fr", "service-public.fr", "justice.fr", "admin.ch", "ch.ch", "gc.ca", "canada.ca",
                   "belgium.be", "fgov.be", "gouv.sn"]
    with st.spinner("Téléchargement…"):
        r = fetch_page(url, domains)
    if not r.ok:
        st.error(r.error)
    else:
        st.success(f"OK — HTTP {r.status} — {len(r.text):,} caractères")
        st.markdown(f"**{r.title}**  \n{r.final_url}  \nRécupéré le {r.fetched_at}")
        st.text_area("Texte extrait", r.text, height=400)
        st.download_button("⬇️ Télécharger (.txt)", r.text, file_name="page_extraite.txt")
        with st.expander(f"Liens de la page ({len(r.links)})"):
            for l in r.links:
                st.markdown(f"- {l}")
