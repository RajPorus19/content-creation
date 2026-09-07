#!/usr/bin/env python3
"""Alimenter le vivier de posts Reddit (reddit_candidates.json).

Récupère les posts « hot » et « top » (jour + semaine) d'une liste de subreddits
via l'API publique `.json`, filtre les histoires suffisamment longues et
populaires, détecte le genre du narrateur, et met à jour le vivier en
préservant le statut « done » des posts déjà traités.

Usage :  python3 scripts/fetch_candidates.py

Secrets : les cookies Reddit sont lus depuis REDDIT_COOKIE (jamais commités).
Sans cookie, l'API publique fonctionne mais peut être limitée en débit.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

REDDIT_COOKIE = "/home/USER/content-creation/reddit_cookie.txt"  # gitignoré
POOL_JSON = "/home/USER/content-creation/reddit_candidates.json"
POOL_MD = "/home/USER/content-creation/reddit_candidats.md"

SUBREDDITS = [
    "relationship_advice", "AmItheAsshole", "AITAH", "JUSTNOMIL",
    "TrueOffMyChest", "offmychest", "confessions", "MaliciousCompliance",
    "pettyrevenge", "entitledparents", "ChoosingBeggars", "JustNoSO",
    "TalesFromRetail",
]

MIN_BODY = 1500   # caractères minimum dans le corps
MIN_SCORE = 100   # score minimum
LISTINGS = ["hot", "top"]  # + paramètre t=day/week pour top

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# Marqueurs de genre du narrateur. « None » = indétectable → voix homme par défaut.
GENDER_RE = re.compile(
    r"\b(?:I(?:'m| am)?|me|my)\s*(?:\(|\[)?\s*(\d{2})\s*[-/ ]?\s*([MF])\s*(?:\]|\))?"  # noqa: E501
)


def _cookies() -> str:
    path = Path(REDDIT_COOKIE)
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8").strip()
    return raw if "=" in raw else f"reddit_session={raw}"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    cookie = _cookies()
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def detect_gender(title: str, selftext: str) -> str | None:
    """Retourne 'homme', 'femme' ou None à partir des marqueurs du texte."""
    for text in (title, selftext[:2000]):
        for m in GENDER_RE.finditer(text):
            return "femme" if m.group(2).upper() == "F" else "homme"
    return None


def fetch_sub(sub: str) -> list[dict]:
    """Récupère et filtre les posts d'un subreddit."""
    posts: dict[str, dict] = {}
    for listing in LISTINGS:
        if listing == "top":
            urls = [f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=50",
                    f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=50"]
        else:
            urls = [f"https://www.reddit.com/r/{sub}/hot.json?limit=50"]
        for url in urls:
            try:
                data = _get(url)
            except Exception:
                continue
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                if d.get("stickied") or d.get("over_18"):
                    continue
                body = d.get("selftext") or ""
                if len(body) < MIN_BODY or d.get("score", 0) < MIN_SCORE:
                    continue
                pid = d.get("id")
                posts[pid] = {
                    "id": pid,
                    "title": d.get("title", ""),
                    "selftext": body,
                    "score": d.get("score", 0),
                    "num_comments": d.get("num_comments", 0),
                    "author": d.get("author", ""),
                    "subreddit": sub,
                    "gender": detect_gender(d.get("title", ""), body),
                    "body_len": len(body),
                    "url": f"https://www.reddit.com{d.get('permalink', '')}",
                }
            time.sleep(1)  # ménager l'API publique
    return list(posts.values())


def main() -> None:
    existing = {}
    if Path(POOL_JSON).exists():
        existing = {p["id"]: p for p in json.load(open(POOL_JSON, encoding="utf-8"))["posts"]}

    collected: dict[str, dict] = {}
    for sub in SUBREDDITS:
        print(f"scan {sub}...", flush=True)
        for p in fetch_sub(sub):
            collected[p["id"]] = p

    # fusionner : garder done/ancien, mettre à jour le reste
    merged: dict[str, dict] = dict(existing)
    for pid, p in collected.items():
        if pid in merged:
            p["done"] = merged[pid].get("done", False)
        else:
            p["done"] = False
        merged[pid] = p

    posts = list(merged.values())
    posts.sort(key=lambda p: p["score"], reverse=True)
    done = sum(1 for p in posts if p["done"])
    payload = {"saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "posts": posts}
    json.dump(payload, open(POOL_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # version lisible
    lines = ["# Vivier de posts Reddit", "",
             f"Total : {len(posts)} | à faire : {len(posts) - done} | faits : {done}", ""]
    for p in posts:
        flag = "✅" if p["done"] else "  "
        g = p["gender"] or "?"
        lines.append(f"{flag} [{p['subreddit']}] score={p['score']} genre={g} | {p['title'][:90]}")
        lines.append(f"     {p['url']}")
    open(POOL_MD, "w", encoding="utf-8").write("\n".join(lines))

    print(f"\nOK : {len(posts)} posts ({done} faits, {len(posts) - done} à faire)")


if __name__ == "__main__":
    main()
