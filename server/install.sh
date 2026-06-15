#!/bin/bash
# Installerar feed-genereringen som ett launchd-jobb på Mac mini-servern.
# Kör EN gång på minin:  bash server/install.sh
# Idempotent — kan köras om för att uppdatera.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.stakbrons.vmfeed"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNNER="$SCRIPT_DIR/run_feed.sh"
LOG="$SCRIPT_DIR/run_feed.log"
INTERVAL=900   # sekunder mellan körningar (15 min)

echo "▸ Repo:    $REPO"
echo "▸ Runner:  $RUNNER"
echo "▸ Plist:   $PLIST"
echo

# 1. Python + beroenden för push.
command -v python3 >/dev/null || { echo "FEL: python3 saknas. Installera Xcode CLT eller python.org."; exit 1; }
echo "▸ python3: $(python3 --version)"
python3 -m pip install --quiet --user google-auth requests >/dev/null 2>&1 \
  && echo "▸ pip: google-auth + requests OK" \
  || echo "  (varning: kunde inte installera google-auth/requests — push kan saknas)"

# 2. Hemligheter.
[ -f "$SCRIPT_DIR/.env" ] \
  && echo "▸ .env: finns" \
  || echo "  ⚠ server/.env saknas — kopiera .env.example och fyll i FOOTBALLDATA_TOKEN (annars ingen resultat-/slutspelsrättning)."
[ -f "$SCRIPT_DIR/fcm_service_account.json" ] \
  && echo "▸ fcm_service_account.json: finns" \
  || echo "  ⚠ server/fcm_service_account.json saknas — lägg dit Firebase service-account-JSON:en (annars ingen morgonpush från minin)."

# 3. Git-push-behörighet (snabbtest mot remote).
if git -C "$REPO" ls-remote -q origin >/dev/null 2>&1; then
  echo "▸ git: kan nå origin"
else
  echo "  ⚠ git kan inte nå origin — kör 'gh auth login' eller lägg en PAT i credential-storen på minin."
fi
chmod +x "$RUNNER"

# 4. Skriv launchd-plisten med absoluta sökvägar.
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUNNER</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST_EOF
echo "▸ Plist skriven."

# 5. Ladda jobbet i den GRAFISKA sessionen (gui/<uid>) så det funkar även när
#    install.sh körs över SSH (vanliga `launchctl load` hamnar då i fel domän).
UID_N="$(id -u)"
launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
if launchctl bootstrap "gui/$UID_N" "$PLIST" 2>/dev/null; then
  echo "▸ launchd-jobbet laddat i gui/$UID_N (var ${INTERVAL}:e sekund)."
else
  launchctl load -w "$PLIST" 2>/dev/null \
    && echo "▸ launchd-jobbet laddat (load-fallback)." \
    || { echo "FEL: kunde inte ladda launchd-jobbet."; exit 1; }
fi
launchctl enable "gui/$UID_N/$LABEL" 2>/dev/null || true

# 6. Kör en gång direkt som röktest.
echo; echo "▸ Testkörning…"
bash "$RUNNER" && echo "▸ Testkörning klar. Logg: $LOG" || echo "  ⚠ Testkörning gav fel — kolla $LOG"

cat <<TIPS

Klart. Nästa steg (en gång, kräver sudo) för att minin aldrig ska somna:
  sudo pmset -a sleep 0 disksleep 0 womp 1
Och slå på automatisk inloggning (Systeminställningar → Användare → Inloggningsval)
så jobbet kör även efter omstart.

Status / loggar:
  launchctl list | grep $LABEL
  tail -f "$LOG"
Avinstallera:
  launchctl unload "$PLIST" && rm "$PLIST"
TIPS
