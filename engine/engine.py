#!/usr/bin/env python3
"""
Moteur « Reddit story → MP4 » (100 % local), style RedditVideoMakerBot.

Pipeline :
  1. Lit un post Reddit (titre + corps, fournis à la main — AUCUN scraping).
  2. Rend une « capture d'écran » du post (carte Reddit mode sombre, Pillow).
  3. TTS Fish Speech (voix off) du titre + corps.
  4. Assemble le MP4 vertical 9:16 : fond gameplay en boucle + carte du post
     en overlay centré + narration.

Aucun upload automatique : le moteur ne fait que produire un fichier MP4 local.

Dépendances : python3 + requests + Pillow (déjà dispo), ffmpeg/ffprobe.
"""

from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

# reddit_screenshot.py est dans le même dossier que ce script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reddit_screenshot import render_reddit_post

# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #
TTS_URL = "http://127.0.0.1:8082/v1/tts"      # fish-server (bind localhost)
VOICE = "narrator"                            # reference_id → references/narrator/
HERE = Path(__file__).resolve().parent
BACKGROUNDS_DIR = HERE / "assets" / "backgrounds"        # clips gameplay réels
BACKGROUND_FALLBACK = HERE / "assets" / "background.mp4"  # dégradé par défaut
OUTPUT_DIR = HERE / "output"
GAP_SECONDS = 0.35                            # silence entre segments audio
SAMPLE_RATE = 44100
VIDEO_W, VIDEO_H = 1080, 1920                 # 9:16 vertical


def choose_background(explicit: str | None) -> Path:
    """Choisit le fond : --background, sinon un clip aléatoire, sinon le dégradé."""
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    clips = sorted(BACKGROUNDS_DIR.glob("*.mp4"))
    if clips:
        return random.choice(clips)
    return BACKGROUND_FALLBACK


# --------------------------------------------------------------------------- #
#  Étape 1 — nettoyage + découpage (pour le TTS, tailles sûres)
# --------------------------------------------------------------------------- #
def clean_text(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2026", "...")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_chunks(text: str, max_len: int = 280) -> list[str]:
    """Découpe en morceaux de taille sûre pour le TTS (aux limites de phrase)."""
    text = clean_text(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_len:
            chunks.append(p)
        else:
            cur = ""
            for piece in re.split(r"(?<=[,;:])\s+", p):
                piece = piece.strip()
                if not piece:
                    continue
                if len(cur) + len(piece) + 1 <= max_len:
                    cur = (cur + " " + piece).strip()
                else:
                    if cur:
                        chunks.append(cur)
                    cur = piece
            if cur:
                chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------- #
#  Étape 2 — TTS Fish Speech (API JSON)
# --------------------------------------------------------------------------- #
def tts(text: str, voice: str = VOICE, format: str = "wav") -> bytes:
    payload = {
        "text": text,
        "format": format,
        "reference_id": voice,
        "normalize": True,
        "max_new_tokens": 1024,
        "chunk_length": 300,
        "temperature": 0.8,
        "top_p": 0.8,
        "repetition_penalty": 1.1,
    }
    resp = requests.post(TTS_URL, json=payload, timeout=600)
    if resp.status_code != 200:
        raise RuntimeError(f"TTS failed (HTTP {resp.status_code}): {resp.text[:300]}")
    return resp.content


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr[:300]}")
    return float(out.stdout.strip())


# --------------------------------------------------------------------------- #
#  Étape 3 — concaténation audio
# --------------------------------------------------------------------------- #
def concat_audio(segments: list[Path], silence: Path, output: Path) -> None:
    lines = []
    for i, seg in enumerate(segments):
        if i > 0:
            lines.append(f"file '{silence}'")
        lines.append(f"file '{seg}'")
    list_file = output.with_suffix(".txt")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(output)],
        check=True, capture_output=True,
    )


def make_silence(path: Path, seconds: float, sr: int = SAMPLE_RATE) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=mono",
         "-t", str(seconds), "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True,
    )


# --------------------------------------------------------------------------- #
#  Étape 4 — assemblage MP4 (fond + screenshot Reddit en overlay + audio)
# --------------------------------------------------------------------------- #
def assemble(background: Path, screenshot: Path, audio: Path, output: Path, duration: float) -> None:
    vf = (
        f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},setsar=1[bg];"
        f"[1:v]scale={VIDEO_W - 110}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
        f"colorchannelmixer=aa=0.95[ov];"
        "[bg][ov]overlay=x=(W-w)/2:y=(H-h)/2[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(background),
        "-i", str(screenshot),
        "-i", str(audio),
        "-filter_complex", vf,
        "-map", "[v]", "-map", "2:a",
        "-t", f"{duration:.3f}",
        "-shortest",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "30",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE),
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Reddit post → MP4 vertical (screenshot Reddit + voix Fish Speech)"
    )
    ap.add_argument("--title", type=str, default="", help="Titre du post")
    ap.add_argument("--text", type=str, default="", help="Corps du post")
    ap.add_argument("--file", type=str, default="", help="Fichier texte contenant le post")
    ap.add_argument("--subreddit", type=str, default="AmItheAsshole")
    ap.add_argument("--username", type=str, default="throwaway_account")
    ap.add_argument("--upvotes", type=int, default=0, help="0 = aléatoire réaliste")
    ap.add_argument("--comments", type=int, default=0, help="0 = aléatoire réaliste")
    ap.add_argument("--voice", type=str, default=VOICE)
    ap.add_argument("--background", type=str, default="", help="Fond (défaut: aléatoire)")
    ap.add_argument("--output", type=str, default="", help="Sortie (défaut: auto)")
    args = ap.parse_args()

    # 1. texte
    body = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    title = clean_text(args.title)
    body = clean_text(body)
    if not title and not body:
        print("❌ Aucun texte fourni (--title / --text / --file)", file=sys.stderr)
        return 1

    if title:
        sep = " " if title.endswith((".", "!", "?")) else ". "
        narration_text = f"{title}{sep}{body}".strip()
    else:
        narration_text = body
    print(f"📝 Post : {len(narration_text)} caractères")

    # 2. rendu du screenshot Reddit
    upvotes = args.upvotes or random.randint(800, 48000)
    comments = args.comments or random.randint(40, 2500)
    print("🖼️  Rendu de la carte Reddit...")
    screenshot_img = render_reddit_post(
        title=title or "(untitled)", body=body,
        subreddit=args.subreddit, username=args.username,
        upvotes=upvotes, comments=comments,
    )
    workdir = Path(tempfile.mkdtemp(prefix="engine_"))
    screenshot = workdir / "post.png"
    screenshot_img.save(screenshot)

    # 3. TTS (par morceaux sûrs, concaténés)
    chunks = split_chunks(narration_text)
    print(f"🎙️  Génération de la voix off ({len(chunks)} segment(s))...")
    segments: list[Path] = []
    for i, chunk in enumerate(chunks, 1):
        print(f"   [{i}/{len(chunks)}] {chunk[:60]}{'...' if len(chunk) > 60 else ''}")
        seg = workdir / f"seg_{i:03d}.wav"
        seg.write_bytes(tts(chunk, voice=args.voice))
        segments.append(seg)

    silence = workdir / "silence.wav"
    make_silence(silence, GAP_SECONDS)
    narration = workdir / "narration.wav"
    print("🔗  Concaténation de l'audio...")
    concat_audio(segments, silence, narration)

    # 4. assemblage
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.output:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or body)[:40].lower()).strip("-") or "story"
        output = OUTPUT_DIR / f"reddit-story-{slug}.mp4"
    else:
        output = Path(args.output)
    print("🎬  Assemblage du MP4 (FFmpeg)...")
    narration_dur = audio_duration(narration)
    background = choose_background(args.background or None)
    print(f"   Fond utilisé : {background.name}")
    assemble(background, screenshot, narration, output, narration_dur)

    print(f"\n✅ MP4 généré : {output}")
    print(f"   Durée : {narration_dur:.1f}s | r/{args.subreddit} | {upvotes} votes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
