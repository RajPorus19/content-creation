#!/usr/bin/env bash
# =============================================================================
#  Génère un hash argon2id pour un utilisateur Authelia.
#  Usage : ./scripts/add-user.sh <pseudo> <motdepasse>
#  Puis colle le bloc affiché dans authelia/users_database.yml.
# =============================================================================
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage : $0 <pseudo> <motdepasse>"
  exit 1
fi

USERNAME="$1"
PASSWORD="$2"
IMAGE="authelia/authelia:4.39.20"

HASH=$(docker run --rm "$IMAGE" authelia crypto hash generate argon2 \
         --password "$PASSWORD" --no-confirm 2>/dev/null | grep -oE '\$argon2id\$[^ ]*')

if [ -z "$HASH" ]; then
  echo "Erreur : hash vide — l'image $IMAGE a-t-elle pu être pullée ?"
  exit 1
fi

cat <<EOF
Hash généré pour « $USERNAME ». Colle ce bloc dans authelia/users_database.yml
(sous la clé "users:") :

  $USERNAME:
    disabled: false
    displayname: "$USERNAME"
    password: "$HASH"
    email: $USERNAME@example.com
    groups:
      - admins

Puis relance :  docker compose restart authelia
EOF
