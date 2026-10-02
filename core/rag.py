"""RAG local : découpage, ingestion de sources, recherche hybride (mots-clés FTS5 + vecteurs) filtrée
par pays, domaine, statut et date d'application."""
import io
import re
from datetime import date

import numpy as np

from . import db, llm


def chunk_text(text: str, size=1200, overlap=150) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= size:
            cur = f"{cur}\n\n{p}" if cur else p
            continue
        if cur:
            chunks.append(cur)
        while len(p) > size:
            chunks.append(p[:size])
            p = p[size - overlap:]
        cur = p
    if cur:
        chunks.append(cur)
    return chunks


def extract_text(name: str, data: bytes) -> str:
    if name.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    return data.decode("utf-8", errors="ignore")


def ingest(meta: dict, text: str):
    """Ajoute une source et ses passages. Retourne (source_id, nb_passages, avertissement|None)."""
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Texte vide.")
    embs, warn = [None] * len(chunks), None
    try:
        embs = list(llm.embed(chunks))
    except Exception as e:  # la recherche par mots-clés reste disponible
        warn = f"Embeddings indisponibles ({e}). Recherche par mots-clés uniquement pour cette source."
    return db.add_source(meta, chunks, embs), len(chunks), warn


def retrieve(query: str, country: str, domain: str, k=6) -> list[dict]:
    today = date.today().isoformat()
    scores: dict[int, float] = {}
    for r, cid in enumerate(db.fts_search(query, country, domain, today)):
        scores[cid] = scores.get(cid, 0) + 1 / (60 + r)
    try:
        cands = db.vector_candidates(country, domain, today)
        if cands:
            qv = llm.embed([query], "RETRIEVAL_QUERY")[0]
            ids = [c[0] for c in cands]
            sims = np.vstack([c[1] for c in cands]) @ qv
            for r, i in enumerate(np.argsort(-sims)[:20]):
                scores[ids[i]] = scores.get(ids[i], 0) + 1 / (60 + r)
    except Exception:
        pass
    top = sorted(scores, key=scores.get, reverse=True)[:k]
    return db.chunks_by_ids(top)
