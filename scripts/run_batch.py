#!/usr/bin/env python3
"""Generate N French shorts + schedule them on YouTube (Ma chaîne) + cleanup.

Persistent replacement for the old /tmp/shorts3/run_batch.py (lost on reboot).

Usage: python3 run_batch.py /path/to/batch.json

batch.json = {"posts": [ {slug, subreddit, voice, upvotes, comments, source_id,
                          title, paragraphs[], yt_title, yt_caption, yt_tags[]}, ... ]}

Schedule: the posts are scheduled for the next N evening slots at 18:00 / 19:00 /
20:00 Europe/Paris (today if it's still before 17:00 Paris, else tomorrow). The
brightbean worker auto-publishes each when its scheduled_at passes.
"""
import json, subprocess, sys, os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ENGINE = "/home/USER/content-creation/engine/engine.py"
OUTDIR = Path("/home/USER/content-creation/engine/output")
PY = "/home/USER/.hermes/hermes-agent/venv/bin/python3"
CC = "/home/USER/content-creation"
POOL = "/home/USER/content-creation/reddit_candidates.json"

WS = "[REDACTED]"
ORG = "[REDACTED]"
USER = "[REDACTED]"
YT = "[REDACTED]"  # YouTube "Ma chaîne" @yourchannel

SLOT_HOURS = [18, 19, 20]  # Paris local hours


def slot_iso(day, hour):
    paris = ZoneInfo("Europe/Paris"); utc = ZoneInfo("UTC")
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=paris).astimezone(utc).isoformat()


def next_slots(n):
    paris = ZoneInfo("Europe/Paris")
    now = datetime.now(paris)
    d = now.date() if now.hour < 17 else (now + timedelta(days=1)).date()
    return [slot_iso(d, h) for h in SLOT_HOURS[:n]]


def ffprobe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    posts = cfg["posts"]
    now_mode = "--now" in sys.argv
    slots = next_slots(len(posts))
    if now_mode:
        slots = [datetime.now(timezone.utc).isoformat()] * len(posts)
    print(f"Schedule -> {slots} (now_mode={now_mode})", flush=True)
    results = []

    for i, p in enumerate(posts):
        slug = p["slug"]; paras = p["paragraphs"]
        title = p["title"]; voice = p["voice"]
        up = p.get("upvotes", 0); com = p.get("comments", 0)
        sub = p.get("subreddit", "relationship_advice")
        yt_title, yt_caption, yt_tags = p["yt_title"], p["yt_caption"], p["yt_tags"]
        fname = f"short3-{slug}.mp4"; sched = slots[i]
        print(f"\n===== [{i+1}/{len(posts)}] {slug} (voice={voice}) -> {sched} =====", flush=True)

        txt = Path("/tmp/shorts3") / f"{slug}.txt"
        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_text(title + "\n" + "\n".join(paras) + "\n", encoding="utf-8")

        out = OUTDIR / fname
        r = subprocess.run([PY, ENGINE, "--file", str(txt), "--subreddit", sub,
                            "--username", "throwaway_account", "--speed", "1.25", "--voice", voice,
                            "--upvotes", str(up), "--comments", str(com), "--output", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("GEN_FAIL", r.stderr[-2000:], flush=True); results.append((slug, "GEN_FAIL")); continue
        dur = ffprobe_dur(out)
        print(f"  generated {fname} ({dur:.1f}s)", flush=True)

        subprocess.run(["docker", "cp", str(out), f"cc-brightbean-app:/tmp/{fname}"], check=True)

        create_code = f'''import os
from django.core.files import File
from django.utils import timezone
from datetime import datetime
from apps.workspaces.models import Workspace
from apps.organizations.models import Organization
from apps.media_library.models import MediaAsset
from apps.composer.models import Post, PostMedia, PlatformPost
from apps.social_accounts.models import SocialAccount
from django.contrib.auth import get_user_model
U = get_user_model()
ws = Workspace.objects.get(id={json.dumps(WS)})
org = Organization.objects.get(id={json.dumps(ORG)})
user = U.objects.get(id={json.dumps(USER)})
yt = SocialAccount.objects.get(id={json.dumps(YT)})
fname = {json.dumps(fname, ensure_ascii=False)}; title = {json.dumps(yt_title, ensure_ascii=False)}; caption = {json.dumps(yt_caption, ensure_ascii=False)}; tags = {json.dumps(yt_tags, ensure_ascii=False)}
sched = datetime.fromisoformat({json.dumps(sched)})
size = os.path.getsize("/tmp/" + fname)
asset = MediaAsset.objects.create(organization=org, workspace=ws, uploaded_by=user,
    filename=fname, media_type="video", mime_type="video/mp4", file_size=size,
    width=1080, height=1920, duration={dur!r}, processing_status="completed", title=title)
with open("/tmp/" + fname, "rb") as fh:
    asset.file.save(fname, File(fh), save=True)
post = Post.objects.create(workspace=ws, author=user, title=title, caption=caption, tags=tags)
PostMedia.objects.create(post=post, media_asset=asset, position=0)
pp = PlatformPost.objects.create(post=post, social_account=yt, status="scheduled",
    scheduled_at=sched, platform_extra={{"post_type": "short"}})
print("SCHEDULED", fname, pp.scheduled_at)
'''
        r = subprocess.run(["docker", "compose", "exec", "-T", "brightbean-app",
                            "python", "manage.py", "shell"],
                           input=create_code, text=True, encoding="utf-8", capture_output=True, cwd=CC)
        print("  " + r.stdout.strip(), flush=True)
        if r.returncode != 0:
            print("  CREATE_FAIL", r.stderr[-1500:], flush=True); results.append((slug, "CREATE_FAIL")); continue

        subprocess.run(["docker", "compose", "exec", "-T", "brightbean-app", "sh", "-c", f"rm -f /tmp/{fname}"], capture_output=True)
        try:
            out.unlink(); print(f"  deleted local {fname}", flush=True)
        except OSError:
            pass
        results.append((slug, "OK"))

    # mark done only for successes
    ok_ids = {posts[i]["source_id"] for i, (_, st) in enumerate(results)
              if st == "OK" and i < len(posts) and posts[i].get("source_id")}
    if ok_ids and os.path.exists(POOL):
        pool = json.load(open(POOL, encoding="utf-8"))
        for pp in pool["posts"]:
            if pp["id"] in ok_ids:
                pp["done"] = True
        pool["done_ids"] = sorted(set(pool.get("done_ids", [])) | ok_ids)
        json.dump(pool, open(POOL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  marked done: {sorted(ok_ids)}", flush=True)

    print("\n===== SUMMARY =====", flush=True)
    for slug, st in results:
        print(f"{slug}: {st}", flush=True)


if __name__ == "__main__":
    main()
