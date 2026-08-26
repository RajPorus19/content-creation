#!/usr/bin/env python3
"""
Moteur « Reddit story → MP4 » (100 % local).

Pipeline :
  1. Lit un post Reddit (titre + texte, fournis à la main — AUCUN scraping).
  2. Découpe le texte en phrases.
  3. TTS Fish Speech (API /v1/tts) phrase par phrase → segments audio.
  4. Concatène l'audio (avec un léger silence entre phrases).
  5. Génère des sous-titres synchronisés (ASS).
  6. Assemble le MP4 vertical 9:16 (fond en boucle + sous-titres + audio).

Aucun upload automatique : le moteur ne fait que produire un fichier MP4 local
que tu publies ensuite toi-même (ex. via BrightBean).

Dépendances : python3 + requests (déjà dispo), ffmpeg/ffprobe (déjà installés).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import requests

# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #
TTS_URL = "http://127.0.0.1:8082/v1/tts"      # fish-server (bind localhost)
VOICE = "narrator"                            # reference_id → references/narrator/
HERE = Path(__file__).resolve().parent
BACKGROUND = HERE / "assets" / "background.mp4"
OUTPUT_DIR = HERE / "output"
GAP_SECONDS = 0.35                            # silence entre phrases
SAMPLE_RATE = 44100

# --------------------------------------------------------------------------- #
#  Étape 1 — nettoyage + découpage en phrases
# --------------------------------------------------------------------------- #
def clean_text(text: str) -> str:
    """Normalise les espaces / retours à la ligne / artefacts Reddit basiques."""
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2026", "...")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str, max_len: int = 280) -> list[str]:
    """Découpe en phrases ; les phrases trop longues sont re-découpées."""
    text = clean_text(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    sentences: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_len:
            sentences.append(p)
        else:
            # re-découpe aux virgules / clauses pour rester sous max_len
            sentences.extend(_split_long(p, max_len))
    return sentences


def _split_long(segment: str, max_len: int) -> list[str]:
    chunks = []
    current = ""
    for piece in re.split(r"(?<=[,;:])\s+", segment):
        piece = piece.strip()
        if not piece:
            continue
        if len(current) + len(piece) + 1 <= max_len:
            current = (current + " " + piece).strip()
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
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
        raise RuntimeError(
            f"TTS failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )
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
#  Étape 3 — concaténation audio (FFmpeg concat demuxer + silences)
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
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r={sr}:cl=mono", "-t", str(seconds),
         "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True,
    )


# --------------------------------------------------------------------------- #
#  Étape 4 — sous-titres ASS
# --------------------------------------------------------------------------- #
def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def wrap_ass(text: str, width: int = 30) -> str:
    return "\\N".join(textwrap.wrap(text, width=width))


def build_ass(cues: list[tuple[float, float, str]], font: str = "DejaVu Sans") -> str:
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},62,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,60,60,200,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for start, end, txt in cues:
        events.append(
            f"Dialogue: 0,{fmt_ts(start)},{fmt_ts(end)},Default,,0,0,0,,{wrap_ass(txt)}"
        )
    return header + "\n".join(events) + "\n"


# --------------------------------------------------------------------------- #
#  Étape 5 — assemblage MP4 (FFmpeg)
# --------------------------------------------------------------------------- #
def assemble(background: Path, audio: Path, ass: Path, output: Path, duration: float) -> None:
    # Échappe les caractères spéciaux du chemin ASS pour le filtre subtitles
    ass_esc = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    vf = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,"
        f"subtitles='{ass_esc}'[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(background),
        "-i", str(audio),
        "-filter_complex", vf,
        "-map", "[v]", "-map", "1:a",
        "-t", f"{duration:.3f}",   # borne la sortie à la durée audio (évite la queue de fond)
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
        description="Reddit post → MP4 vertical (voix Fish Speech + sous-titres)"
    )
    ap.add_argument("--title", type=str, default="", help="Titre du post (hook)")
    ap.add_argument("--text", type=str, default="", help="Corps du post")
    ap.add_argument("--file", type=str, default="", help="Fichier texte contenant le post")
    ap.add_argument("--voice", type=str, default=VOICE, help="reference_id (voix)")
    ap.add_argument("--background", type=str, default=str(BACKGROUND))
    ap.add_argument("--output", type=str, default="", help="Chemin de sortie (défaut: auto)")
    args = ap.parse_args()

    # 1. récupère le texte
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = args.text
    if args.title:
        t = args.title.strip()
        text = f"{t} {text}" if t.endswith((".", "!", "?")) else f"{t}. {text}"
    text = clean_text(text)
    if not text:
        print("❌ Aucun texte fourni (--text / --file / --title)", file=sys.stderr)
        return 1

    print(f"📝 Texte : {len(text)} caractères")

    # 2. découpe en phrases
    sentences = split_sentences(text)
    print(f"✂️  {len(sentences)} phrase(s) détectée(s)")

    # 3. TTS phrase par phrase
    workdir = Path(tempfile.mkdtemp(prefix="engine_"))
    segments: list[Path] = []
    durations: list[float] = []
    print("🎙️  Génération de la voix off (Fish Speech)...")
    for i, sent in enumerate(sentences, 1):
        print(f"   [{i}/{len(sentences)}] {sent[:60]}{'...' if len(sent) > 60 else ''}")
        audio_bytes = tts(sent, voice=args.voice)
        seg = workdir / f"seg_{i:03d}.wav"
        seg.write_bytes(audio_bytes)
        segments.append(seg)
        durations.append(audio_duration(seg))

    # 4. concatène l'audio
    silence = workdir / "silence.wav"
    make_silence(silence, GAP_SECONDS)
    narration = workdir / "narration.wav"
    print("🔗  Concaténation de l'audio...")
    concat_audio(segments, silence, narration)

    # 5. sous-titres
    cues = []
    t = 0.0
    for i, dur in enumerate(durations):
        start = t
        end = t + dur
        cues.append((start, end, sentences[i]))
        t = end + GAP_SECONDS
    ass = workdir / "captions.ass"
    ass.write_text(build_ass(cues), encoding="utf-8")

    # 6. assemble le MP4
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.output:
        slug = re.sub(r"[^a-z0-9]+", "-", sentences[0][:40].lower()).strip("-")
        output = OUTPUT_DIR / f"reddit-story-{slug}.mp4"
    else:
        output = Path(args.output)
    print("🎬  Assemblage du MP4 (FFmpeg)...")
    narration_dur = audio_duration(narration)
    assemble(Path(args.background), narration, ass, output, narration_dur)

    total = sum(durations) + GAP_SECONDS * (len(durations) - 1)
    print(f"\n✅ MP4 généré : {output}")
    print(f"   Durée audio : {total:.1f}s | {len(sentences)} phrases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
