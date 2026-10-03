"""JURIA — assistant juridique IA (prototype Streamlit + Gemini).  Lancer : streamlit run app.py"""
import hashlib
import json
import secrets
import uuid
from datetime import date
from pathlib import Path

import streamlit as st

import core.db as db
import core.llm as llm
import core.rag as rag
import core.pipeline as pl
import core.security as sec
from core.config import (ADMIN_EMAILS, AI_NOTICE, COUNTRIES, DOMAINS, GEMINI_MODEL, LANGS, MAX_UPLOAD_MB,
                         SHORT_NOTICE, STATUSES, UPLOAD_DIR)

st.set_page_config(page_title="JURIA — Assistant juridique IA", page_icon="⚖️", layout="centered")
db.init()
st.markdown("""<style>
html, body, [class*="css"] {font-size:18px;}
.block-container {max-width:820px; padding-top:2rem;}
.stButton>button, .stDownloadButton>button {min-height:3.4rem; border-radius:16px; font-weight:600;}
</style>""", unsafe_allow_html=True)

P_HOME, P_CHAT, P_DOC, P_CASE = "🏠 Accueil", "💬 Conversation", "📄 Analyser un document", "📁 Mon dossier"
P_SRC, P_GEN, P_HELPER, P_PRIV = "🔎 Sources & recherche", "✍️ Générer un document", "⚖️ Trouver une aide aide", "🔐 Confidentialité"
P_FAQ, P_ADMIN = "❓ Aide", "🛠️ Administration"


def go(page):
    st.session_state.page = page


# ------------------------------------------------------------------ utilitaires UI
def risk_banner(risk):
    if risk == "red":
        st.error("🔴 **Situation sensible ou urgente.** Contactez rapidement un avocat, une permanence juridique ou une "
                 "association spécialisée. En cas de danger immédiat, appelez les services d'urgence de votre pays.")
        st.button("⚖️ Trouver une aide juridique", key=f"help{uuid.uuid4().hex}", on_click=go, args=(P_HELPER,))
    elif risk == "orange":
        st.warning("🟠 **À vérifier avec soin.** Confirmez les points importants et les délais auprès de l'autorité "
                   "concernée ou d'un professionnel.")
    else:
        st.success("🟢 Information générale.")


def fmt_source(s):
    if s.get("kind") == "local":
        return (f"**[{s['label']}] {s['title']}** — {s.get('article') or 'sans article'} · vérifié le "
                f"{s.get('last_verified') or 'n/c'} · confiance : {s.get('confidence') or 'n/c'}"
                + (f" · [lien]({s['url']})" if s.get("url") else ""))
    return f"🌐 [{s['title']}]({s['url']})"


def new_case_form(uid, key):
    with st.form(key):
        country = st.selectbox("Dans quel pays votre situation se déroule-t-elle ?", list(COUNTRIES))
        domain = st.selectbox("Quel est votre problème ?", DOMAINS)
        title = st.text_input("Nom du dossier (facultatif)")
        if st.form_submit_button("Créer le dossier", type="primary", use_container_width=True):
            cid = db.create_case(uid, title.strip() or f"{domain.split(' ')[0]} — {country}", country, domain)
            db.audit(uid, "case_created", str(cid))
            st.session_state["_new_case"] = cid
            st.rerun()


def need_case(u):
    st.info("Créez d'abord un dossier : il regroupe vos échanges et documents (isolés des autres dossiers).")
    new_case_form(u["id"], "new_case_main")


# ------------------------------------------------------------------ authentification
def auth_view():
    st.title("⚖️ JURIA")
    st.caption("Assistant juridique IA — comprendre vos droits, préparer votre dossier")
    st.info(AI_NOTICE)
    t1, t2 = st.tabs(["Se connecter", "Créer un compte"])
    with t1:
        email = st.text_input("E-mail", key="le")
        pw = st.text_input("Mot de passe", type="password", key="lp")
        if st.button("Se connecter", type="primary", use_container_width=True):
            u = db.get_user(email.strip().lower())
            if u and sec.verify_password(pw, u["pw_hash"], u["salt"]):
                if not u["is_active"]:
                    st.error("Ce compte est suspendu. Contactez l'administrateur.")
                else:
                    if u["email"] in ADMIN_EMAILS and not u["is_admin"]:
                        db.set_user_flag(u["id"], "is_admin", True)
                        u = db.get_user(u["email"])
                    st.session_state.user = u
                    db.touch_login(u["id"])
                    db.audit(u["id"], "login")
                    st.rerun()
            else:
                st.error("Identifiants incorrects.")
    with t2:
        email = st.text_input("E-mail", key="re")
        pw = st.text_input("Mot de passe (10 caractères minimum)", type="password", key="rp")
        c1 = st.checkbox("Je comprends que j'échange avec une intelligence artificielle, pas avec un avocat.")
        c2 = st.checkbox("J'accepte le traitement de mes données pour faire fonctionner l'application "
                         "(elles ne servent pas à entraîner un modèle).")
        if st.button("Créer mon compte", type="primary", use_container_width=True):
            e = email.strip().lower()
            if not sec.valid_email(e):
                st.error("E-mail invalide.")
            elif not sec.strong_password(pw):
                st.error("Mot de passe trop court (10 caractères minimum).")
            elif not (c1 and c2):
                st.error("Les deux consentements sont nécessaires.")
            elif db.get_user(e):
                st.error("Ce compte existe déjà.")
            else:
                h, s = sec.hash_password(pw)
                uid = db.create_user(e, h, s, db.user_count() == 0 or e in ADMIN_EMAILS)
                db.touch_login(uid)
                db.audit(uid, "register")
                st.session_state.user = db.get_user(e)
                st.rerun()


# ------------------------------------------------------------------ barre latérale
def sidebar(u):
    st.session_state.setdefault("page", P_HOME)
    if "_new_case" in st.session_state:
        st.session_state.case_id = st.session_state.pop("_new_case")
    sb = st.sidebar
    sb.markdown(f"**{u['email']}**")
    pages = [P_HOME, P_CHAT, P_DOC, P_CASE, P_SRC, P_GEN, P_HELPER, P_PRIV, P_FAQ] + ([P_ADMIN] if u["is_admin"] else [])
    sb.radio("Menu", pages, key="page", label_visibility="collapsed")
    cases = db.list_cases(u["id"])
    if cases:
        ids = [c["id"] for c in cases]
        if st.session_state.get("case_id") not in ids:
            st.session_state.case_id = ids[0]
        names = {c["id"]: f"{c['title']} · {c['country']}" for c in cases}
        sb.selectbox("Mon dossier", ids, key="case_id", format_func=names.get)
    with sb.expander("➕ Nouveau dossier"):
        new_case_form(u["id"], "new_case_sb")
    sb.selectbox("Langue des réponses", list(LANGS), key="lang_label")
    sb.toggle("Recherche web sourcée (Google)", value=True, key="use_web")
    sb.toggle("Vérification renforcée (2e passe)", value=False, key="verify")
    if sb.button("Se déconnecter", use_container_width=True):
        db.audit(u["id"], "logout")
        st.session_state.clear()
        st.rerun()


# ------------------------------------------------------------------ pages
def home_view(u, case):
    st.title("Comment pouvons-nous vous aider ?")
    st.caption(SHORT_NOTICE)
    if not case:
        need_case(u)
        return
    st.markdown(f"Dossier actif : **{case['title']}** ({case['country']} · {case['domain']})")
    items = [("🎙️ Parler à l'assistant", P_CHAT), ("⌨️ Écrire ma question", P_CHAT), ("📄 Analyser un document", P_DOC),
             ("📁 Mon dossier", P_CASE), ("🔎 Rechercher dans les sources", P_SRC), ("⚖️ Trouver une aide juridique", P_HELPER),
             ("✍️ Générer un document", P_GEN)]
    cols = st.columns(2)
    for i, (label, page) in enumerate(items):
        cols[i % 2].button(label, key=f"home{i}", on_click=go, args=(page,), use_container_width=True)


def render_msg(m, lang):
    meta = json.loads(m["meta"]) if m["meta"] else {}
    with st.chat_message("user" if m["role"] == "user" else "assistant"):
        st.markdown(m["content"])
        if m["role"] != "assistant":
            return
        if m["kind"] == "answer":
            risk_banner(m["risk"])
        for f in meta.get("flags", []):
            st.caption("⚠️ " + f)
        if meta.get("sources"):
            with st.expander(f"📚 Sources ({len(meta['sources'])})"):
                for s in meta["sources"]:
                    st.markdown(fmt_source(s))
        if m["kind"] == "answer" and st.button("🔊 Écouter", key=f"tts{m['id']}"):
            try:
                st.audio(llm.tts(m["content"], LANGS[lang]), format="audio/mp3")
            except Exception as e:
                st.error(f"Lecture vocale indisponible : {e}")


def chat_view(u, case, lang):
    st.subheader(f"💬 {case['title']}")
    st.caption(f"Assistant juridique IA — {case['domain']} — {case['country']} · Statut : intelligence artificielle")
    st.caption(SHORT_NOTICE)
    if db.country_source_count(case["country"]) == 0:
        st.warning(f"Base juridique locale non disponible pour {case['country']} : les réponses reposent sur la recherche "
                   "web sourcée (si activée) et sur les connaissances générales du modèle, à vérifier.")
    hist = db.get_messages(case["id"], u["id"])
    for m in hist:
        render_msg(m, st.session_state.get("lang_label", "Français"))
    audio = st.audio_input("🎙️ Parler à l'assistant")
    q = st.chat_input("Écrivez votre question…")
    if audio:
        raw = audio.getvalue()
        h = hashlib.md5(raw).hexdigest()
        if st.session_state.get("last_audio") != h:
            st.session_state.last_audio = h
            with st.spinner("Transcription…"):
                try:
                    q = llm.transcribe(raw)
                except Exception as e:
                    st.error(f"Transcription impossible : {e}")
    if q and q.strip():
        db.add_message(case["id"], "user", "user", q)
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"), st.spinner("Analyse en cours…"):
            try:
                res = pl.respond(q, case, u["id"], hist, lang, st.session_state.get("use_web", True),
                                 st.session_state.get("verify", False))
            except Exception as e:
                res = {"kind": "error", "text": f"Une erreur est survenue : {e}", "risk": None, "sources": [], "flags": []}
        db.add_message(case["id"], "assistant", res["kind"], res["text"], res["risk"],
                       {"sources": res["sources"], "flags": res["flags"]})
        db.audit(u["id"], "question", f"case={case['id']} kind={res['kind']} risk={res['risk']}")
        st.rerun()


def docs_view(u, case, lang):
    st.header("📄 Analyser un document")
    st.caption("Photo, image ou PDF. L'IA lit le document (OCR intégré), n'invente aucun délai et signale ce qui est illisible.")
    files = st.file_uploader("Importer un ou plusieurs documents", type=["pdf", "png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True)
    with st.expander("📷 Photographier un document"):
        cam = st.camera_input("Photo")
    items = [(f.name, f.type, f.getvalue()) for f in files or []]
    if cam:
        items.append((f"photo_{date.today()}.jpg", "image/jpeg", cam.getvalue()))
    if items and st.button("Analyser", type="primary", use_container_width=True):
        for name, mime, data in items:
            if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
                st.error(f"{name} : fichier trop volumineux (max {MAX_UPLOAD_MB} Mo).")
                continue
            with st.spinner(f"Analyse de {name}…"):
                try:
                    analysis = pl.analyze_document(data, mime, name, case, u["id"], lang)
                except Exception as e:
                    st.error(f"{name} : analyse impossible ({e})")
                    continue
            path = UPLOAD_DIR / f"{uuid.uuid4().hex}.enc"
            path.write_bytes(sec.encrypt(data))
            db.add_document(case["id"], name, mime, str(path), analysis)
            db.audit(u["id"], "document_analyzed", f"case={case['id']}")
            st.subheader(name)
            risk_banner(pl.heuristic_risk(analysis))
            st.markdown(analysis)
    st.caption("Les documents sont enregistrés chiffrés dans le dossier actif.")


def case_view(u, case, lang):
    st.header(f"📁 {case['title']}")
    st.caption(f"{case['country']} · {case['domain']}")
    t = st.tabs(["Résumé", "Documents", "Chronologie", "Données"])
    with t[0]:
        for label, kind in [("📝 Résume mon dossier", "summary"), ("📋 Quels documents me manquent ?", "missing"),
                          ("🗓️ Reconstituer la chronologie", "timeline"), ("➡️ Prochains éléments à vérifier", "next")]:
            if st.button(label, key=f"task_{kind}", use_container_width=True):
                with st.spinner("Analyse du dossier…"):
                    try:
                        st.session_state.task_out = (case["id"], pl.case_task(case, u["id"], kind, lang))
                    except Exception as e:
                        st.error(str(e))
        out = st.session_state.get("task_out")
        if out and out[0] == case["id"]:
            st.markdown(out[1])
    with t[1]:
        docs = db.list_documents(case["id"], u["id"])
        if not docs:
            st.info("Aucun document. Utilisez « Analyser un document ».")
        for d in docs:
            with st.expander(f"{d['filename']} — {d['created_at'][:10]}"):
                st.markdown(d["analysis"] or "")
                try:
                    st.download_button("⬇️ Télécharger l'original", sec.decrypt(Path(d["path"]).read_bytes()),
                                       file_name=d["filename"], mime=d["mime"], key=f"dl{d['id']}")
                except Exception:
                    st.caption("Original indisponible.")
    with t[2]:
        with st.form("ev"):
            c1, c2 = st.columns([1, 2])
            d = c1.date_input("Date", value=date.today())
            lab = c2.text_input("Événement (ex. : réception de la décision)")
            if st.form_submit_button("Ajouter") and lab.strip():
                db.add_event(case["id"], d.isoformat(), lab.strip())
                st.rerun()
        for e in db.list_events(case["id"], u["id"]):
            st.markdown(f"- **{e['event_date']}** — {e['label']}")
    with t[3]:
        st.download_button("⬇️ Exporter ce dossier (JSON)",
                           json.dumps([c for c in db.export_user(u["id"])["cases"] if c["id"] == case["id"]],
                                      ensure_ascii=False, indent=2),
                           file_name=f"dossier_{case['id']}.json", mime="application/json")
        if st.checkbox("Je veux supprimer définitivement ce dossier et ses documents") and st.button("🗑️️ Supprimer", type="primary"):
            db.delete_case(case["id"], u["id"])
            db.audit(u["id"], "case_deleted", str(case["id"]))
            st.session_state.pop("case_id", None)
            st.rerun()


def sources_view():
    st.header("🔎 Sources & recherche")
    st.caption("Recherche dans la base juridique LOCALE (textes ajoutés par l'administrateur).")
    cov = db.coverage()
    if cov:
        st.dataframe(cov, use_container_width=True, hide_index=True)
    else:
        st.warning("Aucune source locale pour l'instant. L'administrateur doit ajouter des textes officiels "
                   "(page Administration). Aucune donnée juridique n'est fournie par défaut.")
    c1, c2 = st.columns(2)
    country = c1.selectbox("Pays", list(COUNTRIES), key="sc")
    domain = c2.selectbox("Domaine", DOMAINS, key="sd")
    q = st.text_input("Votre recherche")
    if q and st.button("Rechercher", type="primary", use_container_width=True):
        hits = rag.retrieve(q, country, domain, k=8)
        if not hits:
            st.info("Aucun passage trouvé (statut « en vigueur » et date d'application respectés).")
        for h in hits:
            with st.expander(f"{h['title']} — {h.get('article') or 'sans article'}"):
                st.caption(f"{h['country']} · {h.get('jurisdiction') or ''} · statut : {h['status']} · en vigueur depuis "
                           f"{h.get('effective_from') or 'n/c'} · vérifié le {h.get('last_verified') or 'n/c'} · "
                           f"confiance : {h.get('confidence') or 'n/c'}")
                st.write(h["content"])
                if h.get("url"):
                    st.markdown(f"[Source officielle]({h['url']})")


def gen_view(u, case, lang):
    st.header("✍️ Générer un document")
    st.warning("Tout document généré est un **projet à vérifier** avant utilisation ou envoi. Aucune garantie d'acceptation.")
    kind = st.selectbox("Type de document", pl.DRAFT_KINDS)
    instr = st.text_area("Précisions (destinataire, faits, ce que vous demandez…)", height=140)
    if st.button("Générer le projet", type="primary", use_container_width=True):
        with st.spinner("Rédaction…"):
            try:
                st.session_state.draft = pl.draft_document(case, u["id"], kind, instr, lang)
                db.audit(u["id"], "draft_generated", kind)
            except Exception as e:
                st.error(str(e))
    if st.session_state.get("draft"):
        st.markdown(st.session_state.draft)
        st.download_button("⬇️ Télécharger (.txt)", st.session_state.draft, file_name="projet_juria.txt")


def helper_view(u, case):
    st.header("⚖️ Trouver une aide juridique")
    st.caption("Recherche web d'avocats, associations, permanences et services publics. Vérifiez toujours les informations.")
    c1, c2 = st.columns(2)
    country = c1.selectbox("Pays", list(COUNTRIES), index=list(COUNTRIES).index(case["country"]) if case else 0, key="hc")
    city = c2.text_input("Ville")
    domain = st.selectbox("Domaine", DOMAINS, key="hd")
    lang_label = st.selectbox("Langue", ["Français", "English", "Autre"], key="hl")
    free = st.checkbox("Aide gratuite uniquement")
    if st.button("Rechercher", type="primary", use_container_width=True):
        with st.spinner("Recherche…"):
            try:
                text, srcs = pl.find_help(country, city, domain, lang_label, free)
                st.markdown(text)
                for s in srcs:
                    st.markdown(fmt_source(s))
            except Exception as e:
                st.error(str(e))
    if country == "France":
        st.markdown("**Points d'entrée officiels (France, à vérifier)** : [justice.fr](https://www.justice.fr) · "
                    "[service-public.fr](https://www.service-public.fr) · [defenseurdesdroits.fr](https://www.defenseurdesdroits.fr) · "
                    "[lacimade.org](https://www.lacimade.org)")


def privacy_view(u):
    st.header("🔐 Confidentialité & données")
    st.markdown("- Mots de passe hachés (scrypt) ; documents originaux chiffrés au repos.\n"
                "- Dossiers isolés par compte. Journal de sécurité des actions (sans contenu).\n"
                "- L'administrateur ne voit ni vos conversations ni vos documents.\n"
                "- Vos textes et documents sont envoyés à l'API Gemini pour produire les réponses ; "
                "la lecture vocale (gTTS) envoie le texte à un service Google.\n"
                "- Vos données ne servent pas à entraîner un modèle depuis cette application.")
    with st.expander("🔑 Changer mon mot de passe"):
        cur = st.text_input("Mot de passe actuel", type="password", key="pw_cur")
        new = st.text_input("Nouveau mot de passe (10 caractères minimum)", type="password", key="pw_new")
        if st.button("Modifier le mot de passe"):
            if not sec.verify_password(cur, u["pw_hash"], u["salt"]):
                st.error("Mot de passe actuel incorrect.")
            elif not sec.strong_password(new):
                st.error("Nouveau mot de passe trop court.")
            else:
                h, s = sec.hash_password(new)
                db.update_password(u["id"], h, s)
                db.audit(u["id"], "password_changed")
                st.success("Mot de passe modifié.")
    st.download_button("⬇️ Exporter toutes mes données (JSON)",
                       json.dumps(db.export_user(u["id"]), ensure_ascii=False, indent=2),
                       file_name="mes_donnees_juria.json", mime="application/json")
    st.divider()
    if st.checkbox("Je veux supprimer définitivement mon compte et toutes mes données") and \
            st.button("🗑️ Supprimer mon compte", type="primary"):
        db.delete_user(u["id"])
        st.session_state.clear()
        st.rerun()


def faq_view():
    st.header("❓ Aide")
    st.info(AI_NOTICE)
    st.markdown("**Comment ça marche ?** Créez un dossier (pays + problème), posez votre question par écrit ou à la voix. "
                "L'IA peut d'abord vous poser quelques questions, puis répond avec ses sources.\n\n"
                "**Que signifient 🟢🟠🔴 ?** Information générale / à vérifier avec soin / sensible ou urgent.\n\n"
                "**Puis-je me fier aux délais ?** Seulement s'ils sont issus d'une source ou de votre document. "
                "Vérifiez-les toujours auprès de l'autorité concernée.\n\n"
                "**L'IA peut-elle se tromper ?** Oui. Pour toute décision importante, consultez un professionnel.")


# ------------------------------------------------------------------ administration
def admin_dashboard():
    items = list(db.stats().items())
    for row in (items[:3], items[3:]):
        for col, (k, v) in zip(st.columns(3), row):
            col.metric(k, v)
    st.subheader("Couverture juridique locale")
    cov = db.coverage()
    if cov:
        st.dataframe(cov, use_container_width=True, hide_index=True)
    else:
        st.warning("Aucune source locale : les réponses reposent sur la recherche web et le modèle.")


def admin_users(u):
    users = db.list_users()
    st.dataframe([{"ID": x["id"], "E-mail": x["email"], "Rôle": "Admin" if x["is_admin"] else "Utilisateur",
                    "Statut": "Actif" if x["is_active"] else "Suspendu", "Inscrit le": x["created_at"][:10],
                    "Dernière connexion": (x["last_login"] or "—")[:16], "Dossiers": x["cases"],
                    "Questions": x["questions"]} for x in users], use_container_width=True, hide_index=True)
    st.caption("Par confidentialité, l'administration ne voit ni les conversations ni les documents des utilisateurs.")
    opts = {x["id"]: x["email"] for x in users}
    uid = st.selectbox("Gérer un compte", list(opts), format_func=opts.get)
    t = next(x for x in users if x["id"] == uid)
    me = t["id"] == u["id"]
    last_admin = bool(t["is_admin"]) and db.admin_count() <= 1
    if me:
        st.info("C'est votre compte : suspension, retrait du rôle admin et suppression sont désactivés.")
    c1, c2 = st.columns(2)
    if c1.button("▶️ Réactiver" if not t["is_active"] else "⏸️ Suspendre", disabled=me, key="u_act",
                 use_container_width=True):
        db.set_user_flag(uid, "is_active", not t["is_active"])
        db.audit(u["id"], "admin_set_active", f"user={uid} active={not t['is_active']}")
        st.rerun()
    if c2.button("⬇️ Retirer admin" if t["is_admin"] else "⬆️ Passer admin", disabled=(me or last_admin), key="u_adm",
                 use_container_width=True):
        db.set_user_flag(uid, "is_admin", not t["is_admin"])
        db.audit(u["id"], "admin_set_admin", f"user={uid} admin={not t['is_admin']}")
        st.rerun()
    if st.button("🔑 Réinitialiser le mot de passe", key="u_pw", use_container_width=True):
        tmp = secrets.token_urlsafe(9)
        h, s = sec.hash_password(tmp)
        db.update_password(uid, h, s)
        db.audit(u["id"], "admin_reset_password", f"user={uid}")
        st.success(f"Mot de passe temporaire pour {t['email']} (affiché une seule fois) :")
        st.code(tmp)
        st.caption("Communiquez-le à l'utilisateur ; il pourra le changer dans « Confidentialité ».")
    with st.expander("🗑️ Supprimer ce compte"):
        st.warning("Supprime définitivement le compte, ses dossiers, messages et documents.")
        if st.checkbox("Je confirme la suppression", key="u_delchk") and st.button(
                "Supprimer définitivement", type="primary", disabled=(me or last_admin), key="u_del"):
            db.delete_user(uid)
            db.audit(u["id"], "admin_deleted_user", f"user={uid}")
            st.rerun()


def admin_sources(u):
    st.warning("N'ajoutez que des textes dont vous avez vérifié la provenance officielle. Sans validation par un juriste, "
               "marquez la confiance « non vérifiée ».")
    with st.form("src"):
        c1, c2 = st.columns(2)
        country = c1.selectbox("Pays", list(COUNTRIES))
        domain = c2.selectbox("Domaine", ["Tous"] + DOMAINS)
        jur = st.text_input("Juridiction (ex. National)")
        title = st.text_input("Titre du texte *")
        article = st.text_input("Article / référence")
        url = st.text_input("URL de la source officielle")
        d1, d2, d3 = st.columns(3)
        pub = d1.text_input("Date du texte (AAAA-MM-JJ)")
        eff = d2.text_input("Entrée en vigueur")
        eff_to = d3.text_input("Fin de validité")
        s1, s2 = st.columns(2)
        status = s1.selectbox("Statut", STATUSES)
        conf = s2.selectbox("Niveau de confiance", ["officielle", "secondaire", "non vérifiée"], index=2)
        up = st.file_uploader("Fichier (.txt, .md, .pdf)", type=["txt", "md", "pdf"])
        pasted = st.text_area("…ou texte collé", height=150)
        if st.form_submit_button("Ajouter la source", type="primary"):
            try:
                for dv in (pub, eff, eff_to):
                    if dv:
                        date.fromisoformat(dv)
                text = rag.extract_text(up.name, up.getvalue()) if up else pasted
                if not title.strip() or not text.strip():
                    raise ValueError("Titre et texte obligatoires.")
                if conf == "officielle" and not url.strip():
                    raise ValueError("Une source « officielle » doit avoir une URL.")
                meta = dict(country=country, jurisdiction=jur, domain=domain, title=title.strip(), article=article,
                            url=url, published=pub, effective_from=eff, effective_to=eff_to, modified=date.today().isoformat(),
                            status=status, confidence=conf, last_verified=date.today().isoformat())
                with st.spinner("Indexation…"):
                    sid, n, warn = rag.ingest(meta, text)
                db.audit(u["id"], "source_added", str(sid))
                st.success(f"Source ajoutée ({n} passages).")
                if warn:
                    st.warning(warn)
            except Exception as e:
                st.error(str(e))
    st.subheader("Sources existantes")
    for s in db.list_sources(50):
        with st.expander(f"#{s['id']} {s['title']} — {s['country']} · {s['status']}"):
            st.caption(f"{s['domain']} · vérifié le {s['last_verified'] or 'n/c'} · confiance : {s['confidence']}")
            ns = st.selectbox("Statut", STATUSES, index=STATUSES.index(s["status"]), key=f"st{s['id']}")
            c1, c2 = st.columns(2)
            if c1.button("Enregistrer", key=f"sv{s['id']}"):
                db.set_source_status(s["id"], ns)
                st.rerun()
            if c2.button("Marquer vérifié aujourd'hui", key=f"vf{s['id']}"):
                db.set_source_status(s["id"], ns, verified_today=True)
                st.rerun()


def admin_view(u):
    st.header("🛠️ Administration")
    t = st.tabs(["📊 Tableau de bord", "👥 Utilisateurs", "📚 Sources", "🧾 Journal"])
    with t[0]:
        admin_dashboard()
    with t[1]:
        admin_users(u)
    with t[2]:
        admin_sources(u)
    with t[3]:
        st.subheader("Journal de sécurité (30 derniers événements)")
        st.dataframe(db.recent_audit(30), use_container_width=True, hide_index=True)
        st.caption(f"Modèle : {GEMINI_MODEL}")


# ------------------------------------------------------------------ routage
def main():
    u = st.session_state.get("user")
    if not u:
        return auth_view()
    fresh = db.get_user_by_id(u["id"])
    if not fresh or not fresh["is_active"]:
        st.session_state.clear()
        st.warning("Session fermée : ce compte est suspendu ou supprimé.")
        return auth_view()
    st.session_state.user = u = fresh
    sidebar(u)
    page = st.session_state.page
    cid = st.session_state.get("case_id")
    case = db.get_case(cid, u["id"]) if cid else None
    lang = LANGS[st.session_state.get("lang_label", "Français")]
    if page == P_HOME:
        home_view(u, case)
    elif page in (P_CHAT, P_DOC, P_CASE, P_GEN) and not case:
        need_case(u)
    elif page == P_CHAT:
        chat_view(u, case, lang)
    elif page == P_DOC:
        docs_view(u, case, lang)
    elif page == P_CASE:
        case_view(u, case, lang)
    elif page == P_GEN:
        gen_view(u, case, lang)
    elif page == P_SRC:
        sources_view()
    elif page == P_HELPER:
        helper_view(u, case)
    elif page == P_PRIV:
        privacy_view(u)
    elif page == P_FAQ:
        faq_view()
    elif page == P_ADMIN and u["is_admin"]:
        admin_view(u)
    st.divider()
    st.caption(SHORT_NOTICE)


main()
