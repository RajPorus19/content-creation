#!/usr/bin/env python3
"""Uploader des shorts vidéo sur TikTok via l'interface web (session cookies).

Le seul outil TikTok du repo. Il ouvre TikTok Studio en Chromium headless,
injecte les cookies de session (compte « yourusername »), upload la vidéo, remplit
la description (sans faire fuiter le nom de fichier), ferme les popups de
première utilisation et publie.

Modes :
  - une vidéo :  python3 scripts/tiktok_upload.py <fichier.mp4> "<description>"
  - un lot     :  python3 scripts/tiktok_upload.py --manifest manifest.json

Le manifest est un JSON : [{"file": "chemin.mp4", "caption": "..."}, ...].
Les fichiers déjà uploadés avec succès sont notés dans TIKTOK_UPLOADED et sont
sautés au prochain run (relance idempotente).

Secrets : les cookies sont lus depuis TIKTOK_COOKIE (jamais commités, voir
.gitignore). Ne pas committer ce fichier.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

TIKTOK_COOKIE = "/home/USER/content-creation/tiktok_cookie.txt"
TIKTOK_UPLOADED = "/home/USER/content-creation/tiktok_upload/uploaded.txt"
UPLOAD_URL = "https://www.tiktok.com/upload?lang=fr"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# Textes des boutons (UI française) qu'il faut fermer / cliquer avant de publier.
COOKIE_ACCEPT = ["Tout autoriser", "Accepter tout", "Accept all"]
TOUR_DISMISS = ["J'ai compris", "Compris", "Got it", "Activer"]
PUBLISH_NOW = ["Publier maintenant", "Publish now"]


def parse_cookies(path: str) -> list[dict]:
    """Parse un header `Cookie:` (name=value;...) en liste pour Playwright."""
    raw = Path(path).read_text(encoding="utf-8").strip()
    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name and value:
            cookies.append({"name": name, "value": value, "domain": ".tiktok.com", "path": "/"})
    return cookies


def click_text(page, texts: list[str]) -> bool:
    """Clique le premier bouton visible dont le texte correspond (force=True)."""
    for text in texts:
        try:
            el = page.query_selector(f"button:has-text('{text}')")
            if el and el.is_visible():
                el.click(force=True)
                time.sleep(1.0)
                return True
        except Exception:
            continue
    return False


def clear_overlays(page) -> None:
    """Ferme cookie banner + tour guidé + modales de première utilisation.

    TikTok Studio 2026 : le tour « Nouvelles fonctionnalités d'édition » et la
    bannière cookies bloquent le clic sur « Publier ». On les ferme en cliquant
    les VRAIS boutons (button:has-text), pas des conteneurs.
    """
    for _ in range(10):
        if not (click_text(page, COOKIE_ACCEPT)
                or click_text(page, ["Décliner les cookies facultatifs", "Decline optional cookies"])
                or click_text(page, TOUR_DISMISS)
                or click_text(page, ["Activer"])):
            break
        time.sleep(0.3)


def set_caption(page, caption: str) -> None:
    """Remplit la description en effaçant d'abord le nom de fichier auto-rempli.

    La description est un DraftEditor (React contenteditable) : il faut
    `focus()` (pas `click(force=True)`, qui ne focusse pas l'éditeur) puis
    `insert_text()` pour gérer emojis + accents.
    """
    cap = page.query_selector("div[contenteditable='true']")
    if not cap:
        return
    cap.focus()
    time.sleep(0.4)
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    time.sleep(0.2)
    page.keyboard.insert_text(caption)


def upload_one(page, video_path: str, caption: str) -> tuple[bool, str]:
    """Upload une vidéo, la décrit et la publie. Retourne (ok, extrait)."""
    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)
    clear_overlays(page)

    file_input = page.wait_for_selector("input[type=file]", state="attached", timeout=30_000)
    file_input.set_input_files(video_path)

    page.wait_for_selector("button:has-text('Publier')", state="attached", timeout=120_000)
    time.sleep(8)
    clear_overlays(page)
    set_caption(page, caption)
    clear_overlays(page)

    publish = page.query_selector("button:has-text('Publier')")
    publish.scroll_into_view_if_needed()
    time.sleep(1)
    publish.click(force=True)
    time.sleep(4)
    # « Continuer à publier ? » → confirme malgré la vérification en cours
    click_text(page, PUBLISH_NOW)
    time.sleep(8)

    text = page.inner_text("body")
    ok = ("en cours d'examen" in text) or ("Créé le" in text) or ("J'aime" in text)
    return ok, text[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description="Uploader des shorts sur TikTok")
    parser.add_argument("video", nargs="?", help="fichier .mp4 (mode une vidéo)")
    parser.add_argument("caption", nargs="?", help="description (mode une vidéo)")
    parser.add_argument("--manifest", help="JSON de [{file, caption}, ...] (mode lot)")
    args = parser.parse_args()

    jobs: list[tuple[str, str]] = []
    if args.manifest:
        jobs = [(j["file"], j["caption"]) for j in json.load(open(args.manifest, encoding="utf-8"))]
    elif args.video and args.caption:
        jobs = [(args.video, args.caption)]
    else:
        parser.error("fournis <video> <caption> OU --manifest manifest.json")

    done = set()
    if Path(TIKTOK_UPLOADED).exists():
        done = set(Path(TIKTOK_UPLOADED).read_text(encoding="utf-8").splitlines())

    cookies = parse_cookies(TIKTOK_COOKIE)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
            user_agent=USER_AGENT,
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        results = []
        for i, (video, caption) in enumerate(jobs, 1):
            if video in done:
                print(f"[{i}/{len(jobs)}] SKIP (déjà uploadé) {video}", flush=True)
                results.append((video, "SKIP"))
                continue
            print(f"[{i}/{len(jobs)}] {video}", flush=True)
            try:
                ok, snippet = upload_one(page, video, caption)
                status = "OK" if ok else "FAIL"
                if ok:
                    with open(TIKTOK_UPLOADED, "a", encoding="utf-8") as fh:
                        fh.write(video + "\n")
                print(f"  -> {status} | {snippet}", flush=True)
            except Exception as exc:
                status = f"ERROR {str(exc)[:120]}"
                print(f"  -> {status}", flush=True)
            results.append((video, status))

        browser.close()

    print("\n===== RÉSUMÉ =====", flush=True)
    for video, status in results:
        print(f"{status:16} {video}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
