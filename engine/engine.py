#!/usr/bin/env python3
"""
Moteur « Reddit story → MP4 » (100 % local), style RedditVideoMakerBot.

Story mode : lit le post en entier (titre + corps), rend une carte façon
screenshot Reddit PAR PARAGRAPHE (elles défilent au fil de la narration),
voix Fish Speech, vitesse de lecture réglable (défaut x1.25).

Aucun scraping, aucun upload automatique : le moteur ne fait que produire un
fichier MP4 local.

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
BACKGROUNDS_DIR = HERE / "assets" / "backgrounds"
BACKGROUND_FALLBACK = HERE / "assets" / "background.mp4"
OUTPUT_DIR = HERE / "output"
GAP_SECONDS = 0.30                            # silence entre segments (avant speed-up)
SAMPLE_RATE = 44100
VIDEO_W, VIDEO_H = 1080, 1920                 # 9:16


def choose_background(explicit: str | None) -> Path:
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    clips = sorted(BACKGROUNDS_DIR.glob("*.mp4"))
    if clips:
        return random.choice(clips)
    return BACKGROUND_FALLBACK


def clean_text(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2026", "...")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def split_paragraphs(body: str) -> list[str]:
    """Découpe le corps en paragraphes (séparés par des sauts de ligne)."""
    paras = [clean_text(p) for p in re.split(r"\n+", body) if clean_text(p)]
    return paras


def build_segments(title: str, body: str) -> list[dict]:
    """Construit la liste des segments de la story : (titre_carte, corps_carte, texte_tts)."""
    paras = split_paragraphs(body) if body else []
    if not paras:
        paras = [body] if body else [""]
    segments: list[dict] = []
    first_para = paras[0] if paras else ""
    tts0 = f"{title} {first_para}".strip() if title else first_para
    segments.append({"title": title, "body": first_para, "tts": tts0})
    for p in paras[1:]:
        segments.append({"title": "", "body": p, "tts": p})
    return segments


# --------------------------------------------------------------------------- #
#  TTS Fish Speech (API JSON)
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
#  Audio : concaténation + accélération (atempo)
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


def speed_up(input_path: Path, output_path: Path, speed: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path), "-filter:a", f"atempo={speed}",
         "-vn", str(output_path)],
        check=True, capture_output=True,
    )


# --------------------------------------------------------------------------- #
#  Assemblage MP4 (story mode : cartes qui défilent + audio accéléré)
# --------------------------------------------------------------------------- #
def assemble_story(
    background: Path,
    cards: list[Path],
    narration: Path,
    starts: list[float],
    durs: list[float],
    output: Path,
    total_dur: float,
) -> None:
    n = len(cards)
    inputs = ["-stream_loop", "-1", "-i", str(background)]
    for c in cards:
        inputs += ["-i", str(c)]
    inputs += ["-i", str(narration)]  # dernier input = audio
    audio_idx = 1 + n

    parts = [
        f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},setsar=1[bg]"
    ]
    for i in range(n):
        parts.append(
            f"[{i+1}:v]scale={VIDEO_W - 110}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
            f"colorchannelmixer=aa=0.95[c{i}]"
        )

    prev = "bg"
    for i in range(n):
        s, d = starts[i], durs[i]
        out_label = "v" if i == n - 1 else f"v{i}"
        parts.append(
            f"[{prev}][c{i}]overlay=x=(W-w)/2:y=(H-h)/2"
            f":enable='between(t,{s:.3f},{s + d:.3f})'[{out_label}]"
        )
        prev = out_label

    vf = ";".join(parts)
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", vf,
        "-map", "[v]", "-map", f"{audio_idx}:a",
        "-t", f"{total_dur:.3f}",
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
        description="Reddit post → MP4 vertical (story mode : cartes + voix Fish Speech)"
    )
    ap.add_argument("--title", type=str, default="")
    ap.add_argument("--text", type=str, default="")
    ap.add_argument("--file", type=str, default="", help="Fichier : 1ère ligne = titre, reste = corps")
    ap.add_argument("--subreddit", type=str, default="relationship_advice")
    ap.add_argument("--username", type=str, default="throwaway_account")
    ap.add_argument("--upvotes", type=int, default=0)
    ap.add_argument("--comments", type=int, default=0)
    ap.add_argument("--speed", type=float, default=1.25, help="Vitesse de lecture (défaut 1.25)")
    ap.add_argument("--voice", type=str, default=VOICE)
    ap.add_argument("--background", type=str, default="")
    ap.add_argument("--output", type=str, default="")
    args = ap.parse_args()

    # 1. texte (titre + corps)
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        title = clean_text(lines[0]) if lines else ""
        body = clean_text("\n".join(lines[1:]))
    else:
        title = clean_text(args.title)
        body = args.text  # garde les sauts de ligne pour les paragraphes
    if not title and not body:
        print("❌ Aucun texte (--title / --text / --file)", file=sys.stderr)
        return 1

    segments = build_segments(title, body)
    print(f"📝 Story : {len(segments)} segment(s) (titre + {len(segments)-1} paragraphe(s))")

    # 2. rendu des cartes + TTS
    workdir = Path(tempfile.mkdtemp(prefix="engine_"))
    upvotes = args.upvotes or random.randint(800, 48000)
    comments = args.comments or random.randint(40, 2500)
    cards: list[Path] = []
    raw_segs: list[Path] = []
    print(f"🖼️  Rendu des cartes + 🎙️ TTS ({args.speed}x)...")
    for i, seg in enumerate(segments, 1):
        print(f"   [{i}/{len(segments)}] {(seg['title'] or seg['body'])[:60]}")
        card_img = render_reddit_post(
            title=seg["title"], body=seg["body"],
            subreddit=args.subreddit, username=args.username,
            upvotes=upvotes, comments=comments,
        )
        card_path = workdir / f"card_{i:02d}.png"
        card_img.save(card_path)
        cards.append(card_path)

        raw = workdir / f"seg_{i:02d}.wav"
        raw.write_bytes(tts(seg["tts"], voice=args.voice))
        raw_segs.append(raw)

    # 3. durées brutes, concat + accélération
    durs_raw = [audio_duration(s) for s in raw_segs]
    silence = workdir / "silence.wav"
    make_silence(silence, GAP_SECONDS)
    narration_raw = workdir / "narration_raw.wav"
    print("🔗  Concaténation + accélération audio...")
    concat_audio(raw_segs, silence, narration_raw)
    narration = workdir / "narration.wav"
    speed_up(narration_raw, narration, args.speed)

    # 4. timing (durées accélérées) + assemblage
    sped_durs = [d / args.speed for d in durs_raw]
    sped_gap = GAP_SECONDS / args.speed
    starts: list[float] = []
    t = 0.0
    for i in range(len(sped_durs)):
        starts.append(t)
        t += sped_durs[i] + sped_gap
    total_dur = sum(sped_durs) + sped_gap * (len(sped_durs) - 1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.output:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "story")[:40].lower()).strip("-") or "story"
        output = OUTPUT_DIR / f"reddit-story-{slug}.mp4"
    else:
        output = Path(args.output)
    print("🎬  Assemblage du MP4 (FFmpeg)...")
    background = choose_background(args.background or None)
    print(f"   Fond : {background.name}")
    assemble_story(background, cards, narration, starts, sped_durs, output, total_dur)

    print(f"\n✅ MP4 généré : {output}")
    print(f"   Durée : {total_dur:.1f}s (x{args.speed}) | r/{args.subreddit} | {len(segments)} cartes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
