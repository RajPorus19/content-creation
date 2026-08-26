# content-creation

Stack **100% locale** (aucun push) de reverse-proxy + authentification forte,
exposée publiquement via un **tunnel Cloudflare**.

| Service     | Rôle                                             |
|-------------|--------------------------------------------------|
| Traefik     | Reverse proxy, routage par chemin `/app`          |
| Authelia    | Authentification : **id + mot de passe + 2FA (TOTP)** |
| cloudflared | Tunnel Cloudflare (sortie, aucun port ouvert)     |

## Architecture

```
Navigateur ──HTTPS──▶ Cloudflare edge ──▶ cloudflared ──▶ traefik:443
                                                              │
                                              forward-auth ──▶ Authelia (2FA)
                                                              │
                                                        app:80 (chemin /app)
```

- Le trafic arrive **par le tunnel** (cloudflared) sur `traefik:443` en interne,
  jamais via un port 80/443 exposé sur l'hôte.
- Traefik route par **chemin** (`/nomdelapp`) via `PathPrefix` + `StripPrefix`.
- Chaque app est derrière le middleware `authelia-auth@file` → impossible d'y
  accéder sans id + mdp + code 2FA.
- Le portail de connexion est sur `https://auth.DOMAIN` (lui-même *bypass*).

## Démarrage

```bash
# 1. Variables d'env
cp .env.example .env
#    → édite DOMAIN + les 3 secrets Authelia (openssl rand -hex 32)
#      + CLOUDFLARE_TUNNEL_TOKEN (token du tunnel)

# 2. Change le domaine dans authelia/configuration.yml (4 occurrences)

# 3. Lance
docker compose up -d
docker compose logs -f   # surveille le démarrage
```

## Configuration côté Cloudflare

Dans le dashboard **Cloudflare Zero Trust → Networks → Tunnels**, pour chaque
hostname public que tu veux exposer :

| Champ           | Valeur                        |
|-----------------|-------------------------------|
| **Service**     | `https://traefik:443`         |
| **TLS**         | « No TLS Verify » (cert auto-signé de Traefik) |

> Le *routing* (quel hostname → quel service) se fait **côté dashboard**, pas
> dans ce repo. Le token seul (`.env`) authentifie le tunnel.

## Certificats

- **À l'origine** (Traefik) : cert **auto-signé** → d'où le « No TLS Verify »
  côté tunnel. Rien à exposer ni à renouveler.
- **En bordure** : Cloudflare gère le TLS public automatiquement.

## Ajouter une app derrière un chemin

Exemple concret dans `docker-compose.yml` (bloc `whoami` commenté). Le principe :

```yaml
labels:
  - "traefik.http.routers.monapp.rule=Host(`${DOMAIN}`) && PathPrefix(`/monapp`)"
  - "traefik.http.middlewares.monapp-strip.stripprefix.prefixes=/monapp"
  - "traefik.http.routers.monapp.middlewares=authelia-auth@file,security-headers@file,monapp-strip"
```

**⚠️ Limite du routage par chemin** : l'app doit savoir qu'elle est servie sous
un sous-chemin (config `base_url` / `root_url` selon l'app). Sinon, passe en
sous-domaine : `Host(`app.${DOMAIN}`)`.

## Apps déployées

### BrightBean Studio — gestion des réseaux sociaux

- **URL** : `https://brightbean.example.com` (sous-domaine 1 niveau → SSL gratuit)
- **Pourquoi un sous-domaine** : Django ne supporte pas proprement le sous-chemin
  `/app`, on sert donc à la racine du domaine (comme le fait son propre
  `docker-compose.prod.yml` avec Caddy).
- **Stack interne** : Django + PostgreSQL 16 + worker (`process_tasks`) + migrate.
- **Services Compose** : `brightbean-postgres`, `brightbean-migrate`,
  `brightbean-app`, `brightbean-worker`.
- **Secrets** (dans `.env`) : `BRIGHTBEAN_SECRET_KEY`, `BRIGHTBEAN_ENCRYPTION_KEY_SALT`,
  `BRIGHTBEAN_POSTGRES_PASSWORD`.

Créer le compte admin :

```bash
docker compose exec brightbean-app python manage.py createsuperuser
```

Mettre à jour l'app (pull + rebuild) :

```bash
cd brightbean-studio && git pull && cd ..
docker compose up -d --build brightbean-migrate brightbean-app brightbean-worker
```



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

- **Dashboard Traefik** (`:8081`) est en local seulement et en clair — à
  protéger ou retirer (`insecure: true` dans `traefik/traefik.yml`).
- Le réseau `proxy` est partagé : toutes les futures apps doivent s'y attacher.
