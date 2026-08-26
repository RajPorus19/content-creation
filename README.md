# content-creation

Stack **100% locale** (aucun push) de reverse-proxy + authentification forte.

| Service  | Rôle                                      |
|----------|-------------------------------------------|
| Traefik  | Reverse proxy, routage par chemin `/app`  |
| Authelia | Authentification : **id + mot de passe + 2FA (TOTP)** |

## Architecture

```
Navigateur ──HTTPS──▶ Traefik ──(forward-auth)──▶ Authelia ──▶ OK ?
                        │                                 │
                        │ app:80                          │ non → redirect portail login
                        ▼
                    https://DOMAIN/nomdelapp
```

- Traefik route par **chemin** (`/nomdelapp`) via `PathPrefix` + `StripPrefix`.
- Chaque app est **derrière le middleware `authelia-auth@file`** → impossible d'y
  accéder sans être connecté (id + mdp + code 2FA).
- Le portail de connexion est sur `https://auth.DOMAIN` (lui-même *bypass*,
  sinon on ne pourrait pas se logger).

## Démarrage

```bash
# 1. Variables d'env (déjà fait si .env existe — il est gitignoré)
cp .env.example .env
#    → édite DOMAIN + les 3 secrets (openssl rand -hex 32)

# 2. Change le domaine dans authelia/configuration.yml (4 occurrences)

# 3. Lance
docker compose up -d
docker compose logs -f   # surveille le démarrage
```

⚠️ **Ports host** : `80`/`443`/`8080` (et `81`) sont pris par le homelab. Ce stack expose
`82` (http), `444` (https), `8081` (dashboard). À changer dans `docker-compose.yml`.

## Certificats

- **Par défaut** : certificat **auto-signé** Traefik → 100% local, mais le
  navigateur affiche un avertissement à accepter.
- **Vrai certificat** (Let's Encrypt) : décommente le bloc `certificatesResolvers`
  dans `traefik/traefik.yml`, mets ton email, puis ajoute
  `tls.certresolver=letsencrypt` sur chaque routeur. Nécessite un domaine public
  + port 80 libre (ou un challenge DNS).

## Ajouter une app derrière un chemin

Exemple concret dans `docker-compose.yml` (bloc `whoami` commenté). Le principe :

```yaml
labels:
  - "traefik.http.routers.monapp.rule=Host(`${DOMAIN}`) && PathPrefix(`/monapp`)"
  - "traefik.http.middlewares.monapp-strip.stripprefix.prefixes=/monapp"
  - "traefik.http.routers.monapp.middlewares=authelia-auth@file,security-headers@file,monapp-strip"
```

**⚠️ Limite du routage par chemin** : l'app doit savoir qu'elle est servie sous
un sous-chemin (config `base_url` / `root_url` selon l'app). Certaines apps ne le
supportent pas → dans ce cas, passe en sous-domaine : `Host(`app.${DOMAIN}`)`.

## Utilisateurs

```bash
# Génère un hash argon2id + le bloc YAML à coller
./scripts/add-user.sh utilisateur "motdepasse"

# … colle le bloc dans authelia/users_database.yml, puis :
docker compose restart authelia
```

Au **premier login**, Authelia force l'enregistrement du 2FA (scan du QR code
avec Google Authenticator / Aegis / etc.), puis demande le code TOTP à chaque
connexion.

## À noter

- **Dashboard Traefik** (`:8081`) est en clair pour l'instant — à protéger ou
  retirer (`insecure: true` dans `traefik/traefik.yml`).
- Le réseau `proxy` est partagé : toutes les futures apps doivent s'y attacher.
