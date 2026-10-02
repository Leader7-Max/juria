"""Pipeline IA de JURIA : triage (questions + risque) -> RAG local -> réponse sourcée -> contrôle qualité."""
import json
import re
from datetime import date, datetime

from google.genai import types

from . import db, llm, rag
from .config import COUNTRIES, LANG_NAMES

SYSTEM = """Tu es JURIA, un assistant juridique fondé sur l'intelligence artificielle. Tu n'es JAMAIS un avocat humain.
RÈGLES ABSOLUES :
1. Tu fournis de l'information juridique, pas un conseil personnalisé ni une représentation.
2. N'invente JAMAIS : article de loi, numéro, délai, jurisprudence, montant, URL, adresse, téléphone. En cas de doute, dis-le.
3. Sépare toujours (a) ce qui est CONFIRMÉ par une source citée ([S1], lien web, ou document de l'utilisateur) de (b) la CONNAISSANCE GÉNÉRALE NON VÉRIFIÉE, à vérifier.
4. Un délai (recours, dépôt, prescription) n'est donné que s'il figure dans une source ou dans un document de l'utilisateur ; sinon écris « délai à vérifier auprès de l'autorité ou d'un professionnel » et conseille d'agir sans attendre.
5. Tiens compte du pays, de la juridiction et de la date : le droit évolue, signale si une règle peut avoir changé.
6. Ton clair, bienveillant, sans jargon inutile, mais précis et approfondi.
7. Prudence : aucune promesse de résultat (« en principe », « il est possible que »).
8. Si les informations sont insuffisantes : « Je ne dispose pas de suffisamment d'informations pour répondre de manière fiable. » puis explique ce qui manque.
9. Urgence (détention, expulsion, mesure d'éloignement, délai proche, enfant en danger, violences) : oriente rapidement vers un professionnel ou un service d'urgence.
10. Réponds dans la langue demandée."""

TRIAGE = """Analyse la demande. Réponds UNIQUEMENT en JSON :
{"needs_clarification": bool, "questions": [max 4 questions courtes], "risk": "green|orange|red", "risk_reasons": ["..."]}
- needs_clarification = true SEULEMENT si des informations ESSENTIELLES manquent (selon le domaine : pays, autorité, date et type de décision, nationalité, statut de séjour, situation familiale, âge des enfants, etc.) et ne figurent ni dans la demande, ni dans le dossier, ni dans l'historique. Jamais de questions inutiles.
- risk : red = urgence ou droit important menacé (délai de recours proche, expulsion, détention, procédure pénale, enfant en danger, décision judiciaire, prescription) ; orange = points à vérifier avec soin ; green = information générale."""

ANSWER_FORMAT = """FORMAT (Markdown, approfondi mais lisible par un non-juriste) :
## Réponse en bref
## Analyse détaillée
(règles applicables, conditions, exceptions fréquentes, étapes de la procédure, autorités compétentes)
## Délais et recours à vérifier
(uniquement les délais issus des sources/documents ; sinon « à vérifier »)
## Démarches et pièces à réunir
## Prochaines étapes concrètes
## Ce qui est confirmé / ce qui ne l'est pas
(liste : « Confirmé [S#] ou source web » versus « Connaissance générale non vérifiée »)
## Quand consulter un professionnel
Termine par une phrase rappelant que tu es une IA."""

RED = ["oqtf", "obligation de quitter", "garde à vue", "rétention", "détention", "expulsion", "expulsé",
       "enlèvement", "violences", "menaces de mort", "mandat d'arrêt", "audience demain", "interdiction de territoire",
       "reconduite", "refoulement", "retrait des enfants", "placement de l'enfant", "ordonnance de protection"]
ORANGE = ["délai", "recours", "tribunal", "audience", "prescription", "refus", "rejet", "retrait de titre",
          "divorce", "garde", "pension", "huissier", "mise en demeure", "licenci", "convocation"]
RANK = {"green": 0, "orange": 1, "red": 2}


def heuristic_risk(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in RED):
        return "red"
    return "orange" if any(k in t for k in ORANGE) else "green"


def max_risk(*r: str) -> str:
    return max(r, key=lambda x: RANK.get(x, 1))


# ---------- contexte ----------
def case_context(case, uid, max_docs=6, max_chars=2500) -> str:
    docs = db.list_documents(case["id"], uid)[-max_docs:]
    ev = db.list_events(case["id"], uid)
    parts = [f"DOSSIER : {case['title']} — pays : {case['country']} — domaine : {case['domain']}"]
    if docs:
        parts.append("DOCUMENTS ANALYSÉS DU DOSSIER :\n" + "\n".join(
            f"- {d['filename']} ({d['created_at'][:10]}) : {(d['analysis'] or '')[:max_chars]}" for d in docs))
    if ev:
        parts.append("CHRONOLOGIE SAISIE :\n" + "\n".join(f"- {e['event_date']} : {e['label']}" for e in ev))
    return "\n\n".join(parts)


def history_text(msgs, n=10) -> str:
    return "\n".join(f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'} : {m['content'][:1500]}"
                     for m in msgs[-n:]) or "(aucun)"


def format_local(chunks):
    blocks, src = [], []
    for i, c in enumerate(chunks, 1):
        label = f"S{i}"
        blocks.append(f"[{label}] {c['title']} — {c.get('article') or 'sans article'} — {c.get('jurisdiction') or ''} — "
                      f"statut : {c['status']} — en vigueur depuis : {c.get('effective_from') or 'n/c'} — "
                      f"dernière vérification : {c.get('last_verified') or 'n/c'} — {c.get('url') or ''}\n{c['content']}")
        src.append({"kind": "local", "label": label, "title": c["title"], "article": c.get("article"),
                    "url": c.get("url"), "last_verified": c.get("last_verified"), "confidence": c.get("confidence")})
    return "\n\n".join(blocks), src


# ---------- triage ----------
def triage(question, ctx, hist) -> dict:
    prompt = f"{TRIAGE}\n\nDATE : {date.today()}\n{ctx}\n\nHISTORIQUE :\n{hist}\n\nDEMANDE : {question}"
    try:
        txt, _ = llm.generate(prompt, SYSTEM, json_mode=True, temperature=0)
        d = json.loads(txt)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    risk = d.get("risk") if d.get("risk") in RANK else "orange"
    return {"needs_clarification": bool(d.get("needs_clarification")),
            "questions": [str(x) for x in d.get("questions", [])][:4], "risk": risk}


# ---------- contrôle qualité ----------
def quality_checks(text, local_src, web_src) -> list[str]:
    flags = []
    has_src = bool(local_src or web_src)
    if not has_src:
        flags.append("Aucune source n'a pu être rattachée à cette réponse : considérez-la comme une orientation "
                     "générale NON vérifiée.")
    if re.search(r"\b\d+\s*(jours?|mois|semaines?|ans?)\b", text, re.I):
        flags.append("Des délais sont mentionnés : vérifiez-les sur la décision reçue ou auprès de l'autorité." if has_src
                     else "Un délai est mentionné sans source : à vérifier impérativement avant d'agir.")
    if re.search(r"\b(certainement|à coup sûr|garanti|sans aucun doute|vous gagnerez|vous allez obtenir)\b", text, re.I):
        flags.append("Formulation trop catégorique détectée : aucun résultat n'est garanti.")
    year_ago = date.today().replace(year=date.today().year - 1).isoformat()
    for s in local_src:
        if not s.get("last_verified") or s["last_verified"] < year_ago:
            flags.append(f"La source locale « {s['title']} » n'a pas été vérifiée depuis plus d'un an.")
            break
    return flags


def verify_answer(answer, local_block) -> list[str]:
    """2e passe optionnelle : affirmations précises non soutenues par les extraits locaux / contradictions."""
    if not local_block:
        return []
    prompt = ("Compare cette réponse juridique aux extraits de sources. Liste uniquement (1) les affirmations précises "
              "(article, délai, montant, procédure) NON soutenues par les extraits, (2) les contradictions avec les extraits. "
              'Réponds en JSON : {"unsupported": ["..."], "contradictions": ["..."]}\n\n'
              f"EXTRAITS :\n{local_block}\n\nRÉPONSE :\n{answer}")
    try:
        txt, _ = llm.generate(prompt, json_mode=True, temperature=0)
        d = json.loads(txt)
        return ([f"Affirmation non soutenue par les sources locales : {x}" for x in d.get("unsupported", [])[:5]] +
                [f"Contradiction possible : {x}" for x in d.get("contradictions", [])[:5]])
    except Exception:
        return []


# ---------- réponse ----------
def respond(question, case, uid, hist, lang="fr", use_web=True, verify=False) -> dict:
    ctx = case_context(case, uid)
    htxt = history_text(hist)
    clarified = bool(hist) and hist[-1]["kind"] == "clarify"
    t = triage(question, ctx, htxt)
    risk = max_risk(t["risk"], heuristic_risk(question))
    if t["needs_clarification"] and t["questions"] and not clarified:
        qs = "\n".join(f"{i}. {x}" for i, x in enumerate(t["questions"], 1))
        text = ("Pour vous orienter correctement, j'ai besoin de quelques informations :\n\n" + qs +
                "\n\n*Répondez en une seule fois. Si vous ne savez pas, écrivez « je ne sais pas » ou « continuer ».*")
        return {"kind": "clarify", "text": text, "risk": risk, "sources": [], "flags": []}

    prev_user = [m["content"] for m in hist if m["role"] == "user"][-2:]
    chunks = rag.retrieve(" ".join(prev_user + [question]), case["country"], case["domain"])
    local_block, local_src = format_local(chunks)
    sites = COUNTRIES.get(case["country"], [])
    prompt = (f"DATE DU JOUR : {date.today().isoformat()}\nLANGUE DE RÉPONSE : {LANG_NAMES[lang]}\n\n{ctx}\n\n"
              f"HISTORIQUE :\n{htxt}\n\n"
              f"EXTRAITS DE SOURCES LOCALES (cite-les par [S#] ; ignore ceux qui ne concernent pas la question) :\n"
              f"{local_block or '(aucune source locale disponible pour ce pays/domaine)'}\n\n"
              + (f"RECHERCHE WEB : privilégie les sites officiels ({', '.join(sites) or 'sites gouvernementaux et judiciaires du pays'}) "
                 f"et mentionne la date de la règle citée.\n\n" if use_web else "")
              + f"QUESTION ACTUELLE : {question}\n(Si l'utilisateur écrit « continuer », réponds à sa question précédente "
                f"avec les informations disponibles en signalant les limites.)\n\n{ANSWER_FORMAT}")
    text, web_src = llm.generate(prompt, SYSTEM, web=use_web)
    flags = quality_checks(text, local_src, web_src)
    if verify:
        flags += verify_answer(text, local_block)
    return {"kind": "answer", "text": text, "risk": risk, "sources": local_src + web_src, "flags": flags}


# ---------- documents ----------
DOC_PROMPT = """Analyse ce document (courrier, décision administrative ou judiciaire, contrat, justificatif…).
Si le texte est illisible ou partiel, dis-le. Réponds en Markdown avec exactement ces sections :
## Type de document, autorité et date
## Résumé
## Ce que ce document signifie
## Points importants
## Délais mentionnés
(UNIQUEMENT ceux écrits dans le document : cite le passage. N'en invente aucun. Sinon : « Aucun délai lisible — à vérifier ».)
## Recours possibles à vérifier
(ceux mentionnés dans le document ; sinon pistes générales clairement marquées « à vérifier »)
## Documents nécessaires
## Prochaines étapes
## Éléments illisibles ou incertains
## Sources
(le document lui-même ; indique quelle source officielle consulter pour le droit applicable)"""


def analyze_document(data: bytes, mime: str, filename: str, case, uid, lang="fr") -> str:
    ctx = case_context(case, uid, max_docs=4, max_chars=1200)
    prompt = (f"DATE DU JOUR : {date.today().isoformat()}\nLANGUE : {LANG_NAMES[lang]}\nFICHIER : {filename}\n\n{ctx}\n\n"
              f"Si d'autres documents existent dans le dossier, explique ce nouveau document par rapport à eux, "
              f"sans jamais mélanger avec un autre dossier.\n\n{DOC_PROMPT}")
    text, _ = llm.generate([types.Part.from_bytes(data=data, mime_type=mime), prompt], SYSTEM, temperature=0.1)
    return text


TASKS = {
    "summary": "Résume mon dossier de façon claire : situation, documents, état d'avancement, points sensibles.",
    "missing": "Quels documents ou informations semblent manquer à ce dossier pour avancer ? Distingue ce qui est confirmé par les documents de ce qui est une hypothèse à vérifier.",
    "timeline": "Reconstitue la chronologie de mon affaire à partir des documents et événements. Marque clairement les dates incertaines ; n'invente aucune date.",
    "next": "Quels sont les prochains éléments à vérifier (délais, autorités, pièces) ? Ne donne un délai que s'il est dans les documents ; sinon « à vérifier ».",
}


def case_task(case, uid, kind, lang="fr") -> str:
    ctx = case_context(case, uid, max_docs=10, max_chars=3000)
    msgs = history_text(db.get_messages(case["id"], uid), n=12)
    prompt = (f"DATE DU JOUR : {date.today().isoformat()}\nLANGUE : {LANG_NAMES[lang]}\n\n{ctx}\n\n"
              f"CONVERSATIONS RÉCENTES :\n{msgs}\n\nTÂCHE : {TASKS[kind]}")
    text, _ = llm.generate(prompt, SYSTEM)
    return text


DRAFT_BANNER = ("⚠️ PROJET À VÉRIFIER AVANT UTILISATION — généré par une intelligence artificielle, non validé par un "
                "professionnel du droit. Aucune garantie d'acceptation par une autorité.\n\n")
DRAFT_KINDS = ["Lettre / demande administrative", "Contestation / recours gracieux (projet)", "Projet de recours",
               "Mise en demeure (si juridiquement approprié)", "Résumé de dossier", "Chronologie", "Liste de pièces"]


def draft_document(case, uid, kind, instructions, lang="fr") -> str:
    ctx = case_context(case, uid, max_docs=8, max_chars=2000)
    prompt = (f"DATE DU JOUR : {date.today().isoformat()}\nLANGUE : {LANG_NAMES[lang]}\n\n{ctx}\n\n"
              f"TÂCHE : rédige un projet de « {kind} ».\nInstructions de l'utilisateur : {instructions or '(aucune)'}\n"
              "Règles : utilise [À COMPLÉTER] pour toute information manquante ; n'invente ni faits, ni dates, ni références "
              "de textes ; ne cite un article que s'il figure dans le dossier ; ton formel et respectueux. Pour une mise en "
              "demeure, indique d'abord si elle semble appropriée et sinon propose une alternative. À la fin, ajoute une liste "
              "« À vérifier avant envoi » (délais, destinataire, pièces jointes, mode d'envoi).")
    text, _ = llm.generate(prompt, SYSTEM, temperature=0.3)
    return DRAFT_BANNER + text


def find_help(country, city, domain, lang_label, free_only) -> tuple[str, list]:
    prompt = (f"DATE : {date.today().isoformat()}\nRecherche sur le web des structures d'aide juridique RÉELLES : pays = {country}, "
              f"ville = {city or 'non précisée'}, domaine = {domain}, langue souhaitée = {lang_label}, "
              f"{'aide gratuite uniquement' if free_only else 'gratuite ou payante'}.\n"
              "Types : avocats (ordre/barreau), juristes, associations, permanences juridiques, organismes d'aide, services publics.\n"
              "Ne liste QUE des structures trouvées dans les résultats ; pour chacune : nom, type, ce qu'elle fait, ville, site officiel. "
              "N'invente aucun numéro de téléphone ni adresse ; écris « non trouvé » si absent. Termine en rappelant de vérifier "
              "les informations (tarifs, disponibilité) directement auprès de la structure.")
    return llm.generate(prompt, SYSTEM, web=True)
