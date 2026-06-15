#!/bin/bash
# Stakbrons VM-feed — generering på Mac mini-servern.
#
# Körs av launchd var 15:e minut (launchd ÄR loopen — inget eget loopande här).
# En riktig launchd-cron stryps inte som GitHubs schemalagda workflows, så det
# här är den PRIMÄRA backenden. Skriptet: synkar repot, regenererar feeden,
# committar + pushar till GitHub (där appen läser den via CDN), och skickar
# morgonpushen 06 UTC (deduppad mot GitHub-reserven via en commitad markör).
#
# Hemligheter (placeras bredvid skriptet, gitignorerade):
#   server/.env                  -> FOOTBALLDATA_TOKEN=...
#   server/fcm_service_account.json -> Firebase service-account-JSON (för push)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO" || { echo "kan inte cd till repo"; exit 1; }

log() { echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') $*"; }

# Lås så två körningar aldrig överlappar (om en generering drar över 15 min).
LOCK="${TMPDIR:-/tmp}/stakbrons-vmfeed.lock"
if ! mkdir "$LOCK" 2>/dev/null; then log "redan igång (lås finns) — hoppar över"; exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# Hemligheter in i miljön.
if [ -f "$SCRIPT_DIR/.env" ]; then set -a; . "$SCRIPT_DIR/.env"; set +a; fi
if [ -f "$SCRIPT_DIR/fcm_service_account.json" ]; then
  export FCM_SERVICE_ACCOUNT="$(cat "$SCRIPT_DIR/fcm_service_account.json")"
fi

git config user.name  "Stakbrons VM Bot (mini)"
git config user.email "vm-bot@stakbrons.local"

# Utgå alltid från remote HEAD (undviker divergens med GitHub-reserven).
git fetch -q origin main && git reset -q --hard origin/main

regen() {
  python3 scripts/generate.py || { log "::generate FAILADE"; return 1; }
  git add data/
  git diff --staged --quiet && { log "inga ändringar"; return 0; }
  git commit -q -m "feed: $(date -u +'%Y-%m-%d %H:%M UTC') auto (mini)"
}

if regen; then
  for a in 1 2 3; do
    if git push -q; then log "push OK ($a)"; break; fi
    log "push avvisad, synkar ($a/3)"
    git fetch -q origin main && git reset -q --hard origin/main
    regen || break
  done
else
  log "hoppar push pga generate-fel"
fi

# --- Morgonpush 06 UTC (08:xx svensk), en gång per dygn, deduppad via markör ---
HOUR=$(date -u +%H); TODAY=$(date -u +%F); MARK="data/.last_morning_push"
if [ -n "${FCM_SERVICE_ACCOUNT:-}" ] && [ "$HOUR" = "06" ] \
   && { [ ! -f "$MARK" ] || [ "$(cat "$MARK" 2>/dev/null)" != "$TODAY" ]; }; then
  python3 -m pip install --quiet --user google-auth requests >/dev/null 2>&1 || true
  if python3 scripts/send_push.py; then
    echo "$TODAY" > "$MARK"
    git add "$MARK" && git commit -q -m "feed: morgonpush $TODAY (mini)" \
      && git push -q 2>/dev/null || true
    log "morgonpush skickad"
  else
    log "::morgonpush failade"
  fi
fi

log "klart"
