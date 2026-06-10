#!/usr/bin/env bash
# Launch the Atlas site, loading local chat-model config if present.
#
# Sources config/atlas-chat.env (gitignored) so ATLAS_CHAT_* (and any other
# env you put there) are set before the site starts. Without that file the
# site runs with defaults (ATLAS_CHAT_* falls back to the Hermes connection).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/config/atlas-chat.env"

if [ -f "$ENV_FILE" ]; then
  set -a            # export every var assigned while sourcing
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  echo "loaded $ENV_FILE (ATLAS_CHAT_MODEL=${ATLAS_CHAT_MODEL:-<unset>})"
else
  echo "no $ENV_FILE; using defaults (ATLAS_CHAT_* -> Hermes connection)"
fi

exec python -m aishelf.site
