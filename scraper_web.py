"""Module indépendant : récupère et nettoie le texte d'une page web publique.

Aucune dépendance vers core/ ni app.py. Dépendances : requests, beautifulsoup4.
Usage :
    from scraper_web import fetch_page
    r = fetch_page("https://www.service-public.fr/...")
    if r.ok: print(r.title, r.text)
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
           "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"}
TIMEOUT = 15                      # secondes
MAX_BYTES = 3 * 1024 * 1024       # 3 Mo maximum téléchargés
MAX_REDIRECTS = 5

# Balises supprimées avant extraction du texte.
NOISE_TAGS = ["script", "style", "noscript", "template", "iframe", "svg", "canvas", "form",
              "header", "footer", "nav", "aside", "button", "input", "select", "textarea"]
# Fragments de class/id typiques des menus, bandeaux cookies, publicités, etc.
NOISE_HINTS = re.compile(r"(cookie|consent|banner|breadcrumb|menu|navbar|sidebar|share|social|"
                         r"newsletter|popup|modal|advert|promo|skip-link|pagination)", re.I)
MAIN_SELECTORS = ["main", "article", "[role=main]", "#content", "#main", ".content", ".main-content"]


@dataclass
class PageResult:
    url: str
    ok: bool = False
    status: int | None = None
    final_url: str = ""
    title: str = ""
    text: str = ""
    fetched_at: str = ""
    error: str = ""
    links: list[str] = field(default_factory=list)


class ScrapeError(Exception):
    pass
def _check_url(url: str, allowed_domains: list[str] | None = None) -> str:
    """Valide l'URL : http(s) uniquement, pas d'adresse interne (anti-SSRF), domaines autorisés optionnels."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ScrapeError("URL invalide : seules les adresses http(s) sont acceptées.")
    host = p.hostname.lower()
    if allowed_domains and not any(host == d or host.endswith("." + d) for d in allowed_domains):
        raise ScrapeError(f"Domaine non autorisé : {host}")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise ScrapeError(f"Domaine introuvable : {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ScrapeError("Adresse interne refusée pour des raisons de sécurité.")
    return url


def _download(url: str, allowed_domains) -> tuple[requests.Response, bytes, str]:
    """Télécharge en suivant manuellement les redirections (chacune est revalidée)."""
    for _ in range(MAX_REDIRECTS + 1):
        url = _check_url(url, allowed_domains)
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=False)
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, resp.headers.get("Location", ""))
            resp.close()
            continue
        ctype = resp.headers.get("Content-Type", "").lower()
        if resp.status_code == 200 and "html" not in ctype and "text" not in ctype:
            resp.close()
            raise ScrapeError(f"Type de contenu non pris en charge ({ctype or 'inconnu'}). Seules les pages HTML/texte le sont.")
        data = b""
        for chunk in resp.iter_content(65536):
            data += chunk
            if len(data) > MAX_BYTES:
                resp.close()
                raise ScrapeError("Page trop volumineuse (limite 3 Mo).")
        return resp, data, url
    raise ScrapeError("Trop de redirections.")
def clean_html(html: str, base_url: str = "") -> tuple[str, str, list[str]]:
    """Retourne (titre, texte nettoyé, liens). Supprime scripts, styles, menus, pieds de page, etc."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "") or \
            (soup.h1.get_text(" ", strip=True) if soup.h1 else "")
    for t in soup(NOISE_TAGS):
        t.decompose()
    for t in soup.find_all(True):
        if t.decomposed if hasattr(t, "decomposed") else False:
            continue
        ident = " ".join(t.get("class", [])) + " " + (t.get("id") or "")
        if ident.strip() and NOISE_HINTS.search(ident) and t.name not in ("html", "body", "main", "article"):
            t.decompose()
    root = None
    for sel in MAIN_SELECTORS:
        root = soup.select_one(sel)
        if root and len(root.get_text(strip=True)) > 200:
            break
        root = None
    root = root or soup.body or soup
    links = []
    for a in root.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.startswith("http") and href not in links:
            links.append(href)
    text = root.get_text("\n", strip=True)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # supprime les lignes très courtes répétées (restes de menus)
    lines, seen = [], {}
    for ln in text.split("\n"):
        if len(ln) < 25:
            seen[ln] = seen.get(ln, 0) + 1
            if seen[ln] > 2:
                continue
        lines.append(ln)
    return title, "\n".join(lines).strip(), links[:50]


def fetch_page(url: str, allowed_domains: list[str] | None = None) -> PageResult:
    """Récupère une page publique et renvoie son texte utile. Ne lève jamais d'exception."""
    res = PageResult(url=url, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        resp, data, final = _download(url, allowed_domains)
        res.status, res.final_url = resp.status_code, final
        if resp.status_code != 200:
            hints = {403: "accès refusé par le site (protection anti-robots)", 404: "page introuvable",
                     429: "trop de requêtes, réessayez plus tard"}
            raise ScrapeError(f"Le site a répondu HTTP {resp.status_code}"
                              f"{' : ' + hints[resp.status_code] if resp.status_code in hints else ''}.")
        enc = resp.encoding if resp.encoding and resp.encoding.lower() != "iso-8859-1" else (resp.apparent_encoding or "utf-8")
        res.title, res.text, res.links = clean_html(data.decode(enc, errors="replace"), final)
        if len(res.text) < 100:
            raise ScrapeError("Peu ou pas de texte extrait (page chargée par JavaScript ou protégée ?).")
        res.ok = True
    except ScrapeError as e:
        res.error = str(e)
    except requests.exceptions.Timeout:
        res.error = "Délai dépassé : le site ne répond pas."
    except requests.exceptions.SSLError:
        res.error = "Erreur de certificat SSL : connexion refusée par sécurité."
    except requests.exceptions.ConnectionError:
        res.error = "Connexion impossible (site hors ligne ou réseau bloqué)."
    except Exception as e:  # filet de sécurité
        res.error = f"Erreur inattendue : {type(e).__name__}"
    return res


if __name__ == "__main__":  # test rapide : python scraper_web.py https://exemple.fr
    import sys
    r = fetch_page(sys.argv[1] if len(sys.argv) > 1 else "https://www.service-public.fr")
    print(r.ok, r.status, r.title, r.error)
    print(r.text[:1500])
