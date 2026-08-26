# Moteur « Reddit story → MP4 »

Pipeline 100 % local : un post Reddit (fourni à la main) → une **vidéo MP4
verticale 9:16** avec **voix off Fish Speech** + **sous-titres** + **fond en
boucle**.

> Aucun scraping, aucun upload automatique. Le moteur ne fait que produire un
> fichier `output/*.mp4` que tu publies ensuite toi-même (ex. BrightBean).

## Prérequis

- `fish-server` qui tourne (API Fish Speech sur `127.0.0.1:8082`).
- `python3` + `requests` (déjà dispo sur l'hôte).
- `ffmpeg` / `ffprobe` (déjà installés).

## Lancer

```bash
# Cas 1 : post collé en argument
python3 engine/engine.py \
  --title "AITA for refusing to pay for my roommate's dog?" \
  --text "So my roommate got a dog without asking me. The dog chewed up my shoes."

# Cas 2 : post dans un fichier texte
python3 engine/engine.py --file /tmp/post.txt

# Options utiles
--voice narrator        # voix (dossier fish-speech/references/<voix>)
--background ...        # fond vertical (défaut: engine/assets/background.mp4)
--output /tmp/x.mp4     # chemin de sortie (défaut: engine/output/*.mp4)
```

## Pipeline

1. Découpe le texte en phrases (et sous-phrases si trop longues).
2. TTS Fish Speech phrase par phrase (voix de référence `narrator`).
3. Concatène l'audio (0.35 s de silence entre phrases).
4. Génère des sous-titres synchronisés (ASS, blanc + contour noir).
5. Assemble le MP4 : fond en boucle + sous-titres + audio (FFmpeg).

## Changer le fond (gameplay)

Le moteur choisit **au hasard** un clip dans `engine/assets/backgrounds/*.mp4`
(s'il n'y en a pas, il retombe sur `engine/assets/background.mp4`, le dégradé).

```bash
# Télécharger un fond gameplay (ici : Minecraft parkour, source RedditVideoMakerBot)
# ⚠️ Il FAUT --cookies-from-browser firefox + --js-runtimes node (sinon YouTube 403)
#     et forcer le codec H.264 (-S vcodec:avc1), l'AV1 faisant planter le décodage ffmpeg.
yt-dlp --cookies-from-browser firefox \
  --js-runtimes "node:$HOME/.nvm/versions/node/v25.8.2/bin/node" \
  -S "vcodec:avc1,res:720" \
  -o "engine/assets/backgrounds/minecraft-parkour.%(ext)s" \
  "https://www.youtube.com/watch?v=n_Dv4JMiwK8"

# Découper un segment de 2 min (stream copy, instantané) puis supprimer le fichier complet
ffmpeg -y -ss 600 -i engine/assets/backgrounds/minecraft-parkour.mp4 -t 120 \
  -c copy -an engine/assets/backgrounds/minecraft-parkour-loop.mp4
rm engine/assets/backgrounds/minecraft-parkour.mp4
```

Ou passe un clip vertical 1080×1920 directement : `--background /chemin/clip.mp4`.

Liste de fonds (Minecraft parkour, GTA, Rocket League, CSGO surf…) dans le repo
[RedditVideoMakerBot](https://github.com/elebumm/RedditVideoMakerBot) →
`utils/background_videos.json`.

## Changer / ajouter une voix

Une voix = un dossier dans `fish-speech/references/` :

```
fish-speech/references/mavoix/
  sample.wav     # ~10 s de voix claire
  sample.lab     # transcription exacte du sample (même basename, ext .lab)
```

Puis `--voice mavoix`.
