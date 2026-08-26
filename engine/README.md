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
# Post depuis un fichier : 1ère ligne = titre, reste = corps (paragraphes)
python3 engine/engine.py --file /tmp/post.txt \
  --subreddit relationship_advice --username ThrowRABoylceen \
  --speed 1.25

# Ou titre + texte en argument
python3 engine/engine.py --title "AITA for..." --text "So my roommate..."

# Options
--subreddit relationship_advice  # r/<subreddit> sur la carte
--username throwaway_dog         # u/<username> sur la carte
--upvotes 762                    # 0 = aléatoire réaliste
--comments 410                   # 0 = aléatoire réaliste
--speed 1.25                     # vitesse de lecture (x1.25 pour capter l'audience)
--voice narrator                 # voix (references/<voix>)
--background /chemin/x.mp4       # fond (défaut: aléatoire dans assets/backgrounds/)
--output /tmp/x.mp4              # sortie (défaut: engine/output/*.mp4)
```

## Pipeline (story mode)

1. Découpe le post en **segments** : titre + 1er paragraphe, puis 1 carte par paragraphe.
2. Rend **une carte façon screenshot Reddit par segment** (elles défilent au fil de la narration).
3. TTS Fish Speech de chaque segment, concatène, puis **accélère l'audio (atempo x1.25)**.
4. Assemble le MP4 : fond gameplay en boucle + cartes en overlay séquencées + narration.

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
