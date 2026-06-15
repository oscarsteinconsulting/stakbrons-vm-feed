# Mac mini som backend för Stakbrons VM-feed

Den här mappen gör Mac minin till **primär backend**: en launchd-cron kör
`scripts/generate.py` var 15:e minut och pushar feeden till GitHub, där appen
läser den via CDN (oförändrat). En riktig launchd-cron stryps **inte** som
GitHubs schemalagda workflows (de droppade ~8 h i sträck nattetid och frös
feeden). GitHub Actions ligger kvar som **reserv** och hoppar in bara om feeden
blivit gammal (minin nere).

```
Mac mini (launchd var 15:e min) ──push──▶ GitHub-repo ──CDN──▶ appen
                                              ▲
                         GitHub Actions (reserv, bara om feeden > 30 min gammal)
```

## Engångsinstallation på minin

1. **Klona repot** (om det inte redan finns på minin) och gå in i det:
   ```bash
   git clone https://github.com/oscarsteinconsulting/stakbrons-vm-feed.git
   cd stakbrons-vm-feed
   ```

2. **Git-push-behörighet** på minin (så den kan pusha):
   ```bash
   gh auth login          # enklast – följ stegen
   # eller: lägg en PAT i credential-storen
   ```

3. **Hemligheter** (gitignorerade, ligger kvar lokalt):
   ```bash
   cp server/.env.example server/.env
   # öppna server/.env och klistra in din FOOTBALLDATA_TOKEN
   # lägg Firebase service-account-JSON:en här (för morgonpushen):
   #   server/fcm_service_account.json
   ```

4. **Installera launchd-jobbet:**
   ```bash
   bash server/install.sh
   ```
   Den kollar beroenden, skriver `~/Library/LaunchAgents/com.stakbrons.vmfeed.plist`,
   laddar jobbet (var 15:e min) och kör ett röktest.

5. **Låt minin vara vaken dygnet runt** (en gång, kräver sudo):
   ```bash
   sudo pmset -a sleep 0 disksleep 0 womp 1
   ```
   Slå även på **automatisk inloggning** (Systeminställningar → Användare och
   grupper → Inloggningsval) så jobbet kör igång efter omstart.

## Drift

- **Status:** `launchctl list | grep com.stakbrons.vmfeed`
- **Logg:**   `tail -f server/run_feed.log`
- **Kör direkt:** `bash server/run_feed.sh`
- **Avinstallera:**
  ```bash
  launchctl unload ~/Library/LaunchAgents/com.stakbrons.vmfeed.plist
  rm ~/Library/LaunchAgents/com.stakbrons.vmfeed.plist
  ```

## Hur reserven samspelar

GitHub-reserven (`.github/workflows/daily.yml`) kollar åldern på
`data/feed.json`. Är den **< 30 min** gör reserven ingenting (minin lever). Är
den äldre regenererar reserven själv. Morgonpushen (06 UTC / 08 svensk) skickas
av minin och deduppas mot reserven via en commitad markör
(`data/.last_morning_push`), så den går ut exakt en gång per dygn oavsett vem
som råkar köra.
