# Moteur « Reddit story → MP4 »

Pipeline 100 % local, style **RedditVideoMakerBot** : un post Reddit (fourni à la
main) → une **vidéo MP4 verticale 9:16** avec **carte du post façon screenshot
Reddit** (mode sombre) en overlay sur un **fond gameplay**, le tout narré par
**Fish Speech**.

> Aucun scraping, aucun upload automatique. Le moteur ne fait que produire un
> fichier `output/*.mp4` que tu publies ensuite toi-même (ex. BrightBean).
> Le screenshot est **rendu localement** (Pillow) à partir du texte — on ne
> touche jamais à Reddit.

## Prérequis

- `fish-server` qui tourne (API Fish Speech sur `127.0.0.1:8082`).
- `python3` + `requests` + `Pillow` (déjà dispo sur l'hôte).
- `ffmpeg` / `ffprobe` (déjà installés).

## Lancer

```bash
python3 engine/engine.py \
  --title "AITA for refusing to pay for my roommate's dog?" \
  --text "So my roommate got a dog without asking me. The dog chewed up my shoes."

# Options
--subreddit AmItheAsshole   # r/<subreddit> affiché sur la carte
--username throwaway_dog    # u/<username> affiché
--upvotes 12800             # 0 = aléatoire réaliste
--comments 342              # 0 = aléatoire réaliste
--voice narrator            # voix (references/<voix>)
--background /chemin/x.mp4  # fond (défaut: aléatoire dans assets/backgrounds/)
--output /tmp/x.mp4         # sortie (défaut: engine/output/*.mp4)
--file /tmp/post.txt        # post depuis un fichier (titre en 1ère ligne)
```

## Pipeline

1. Rend la carte du post (screenshot Reddit mode sombre, Pillow).
2. TTS Fish Speech du titre + corps (par morceaux sûrs, concaténés).
3. Assemble le MP4 : fond gameplay en boucle + carte centrée (opacité 95 %) + narration.

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
