# Stakbrons VM Feed

Publik feed som driver iOS-appen **Stakbrons VM Predictions** under fotbolls-VM 2026.
GitHub Actions genererar nya analyser varje morgon kl 06:15 svensk tid, regenererar
med färska odds kl 08:00 (då skickas också morgonens push-notis via Firebase),
samt uppdaterar oddsen kl 14:00 och 19:00.

**Feed-URL (för appen):**
```
https://raw.githubusercontent.com/oscarsteinconsulting/stakbrons-vm-feed/main/data/feed.json
```

## Modellen — samma analysmetod som hemsidan

Analysen bygger på **Oscars funderingar** (MSS-modellen från VM2026-sajten,
se sidan *Källor & Metod*):

1. **Lagstyrka** = 0.70 · live-Elo (eloratings.net, uppdateras efter varje
   matchdag) + 0.30 · fryst MSS mappad till Elo-skalan (`mss.json` från
   vm2026-facit-repot — prognosen som frystes 11 juni).
   Värdnationerna USA/Mexiko/Kanada får +60 Elo (hemmaplan).
2. **Matchsannolikheter**: Elo-diff → förväntad målskillnad (270 Elo per mål),
   totalmålsbaslinje 2.6, Poisson-rutnät med Dixon-Coles-justering (ρ=−0.08)
   → 1X2, Över/Under, Båda lagen gör mål ur samma rutnät.
3. **Ödmjukhet**: modellens sannolikheter krymps mot Svenska Spels avvigade
   priser (70/30, mer marknadsvikt vid höga odds) innan edge räknas.
4. **Spelarmarknader** (Målgörare, 2+ mål, Skott på mål): avvigat marknadspris
   tiltat med modellens målförväntan relativt marknadens. Odds över 15 hoppas
   över — där dominerar marginalbruset.
5. **Turneringssimulatorn** (`tournament`-sektionen): Monte Carlo-simulering av
   hela slutspelsträdet ger Vinnare/Topp 2/Topp 4/Topp 8/Topp 16 — marknaderna
   avvigas så att sannolikheterna summerar till antalet platser.

### Kategorier (speglar Svenska Spels VM-meny)

| Kategori | Underlag |
|---|---|
| ⚽ Fulltid | 1X2 ur Poisson/Dixon-Coles-rutnätet |
| 🛡 Dubbelchans | 1X/12/X2 ur samma rutnät (marknaden avvigas till summa 2) |
| ⚖️ Handikapp | Asiatisk halvlinje — mest balanserade linjen, P(täcker) ur rutnätet |
| 🥅 Antal mål | Huvudlinje Ö/U + lagmål (Poisson-svans mot lagets λ) |
| 🤝 Båda lagen gör mål | Direkt ur rutnätet |
| 🎯 Korrekt resultat | Hela resultatmarknaden avvigad gemensamt, oddstak 35 |
| ⏱ Halvlek | Halvtid-1X2 + Ö/U första halvlek (λ×0.44) — rättas manuellt |
| 🔁 Halvtid/Fulltid | 9-vägsmarknaden mot produkten av halvleksrutnäten (44/56) |
| 👤 Målgörare | Marknadsankrad med måltilt (som tidigare) |
| 👟 Spelarspecial | 2+ mål och Skott på mål, marknadsankrade |
| 🚩 Hörnor | Marknadsprissatt med mjuk modelltilt [0.92, 1.10] — rättas manuellt |
| 🟨 Kort | Ren avvigning, ingen kortmodell — visas för överblick, rättas manuellt |

Utöver kategorierna innehåller feeden `tournament`-sektionen med
turneringsspel (Vinnare/Topp 2/4/8/16) ur Monte Carlo-simuleringen.

### Värdemärkning

| Märkning | Regel |
|---|---|
| **Spelvärt** | edge ≥ +8 % och odds ≤ 4.0 |
| **Chans** | edge ≥ +8 % och odds > 4.0 (hög utdelning, låg träffchans) |
| **Neutralt** | −4 % < edge < +8 % |
| **Undvik** | edge ≤ −4 % |

Dagsbudgeten fördelas med kvarts-Kelly-vikter över Spelvärt + Chans
(`stakeWeight` i feeden — appen räknar om till kronor mot användarens budget).
Dagar utan värdespel får tom fördelning: budgeten vilar hellre än spelas bort.

## Odds

Svenska Spels riktiga odds via Kambis publika offering-CDN (samma mönster som
[stakbrons-golf-feed](https://github.com/oscarsteinconsulting/stakbrons-golf-feed)):
`listView/football/world_cup_2026/...` för matchlistan, `betoffer/event/{id}`
för dagens matchers ~700 marknader. Kategorierna följer Svenska Spels VM-meny:
Fulltid · Dubbelchans · Handikapp · Antal mål · Båda lagen gör mål ·
Korrekt resultat · Halvlek · Halvtid/Fulltid · Målgörare · Spelarspecial ·
Hörnor · Kort.

## Resultat & rättning

`results`-fältet i feeden ger slutresultat för spelade matcher så appen rättar
1X2/Över-Under/BTTS-spel automatiskt. Källa: football-data.org (gratis-token,
repo-secret `FOOTBALLDATA_TOKEN`) med vm2026-facit-repots `results.json` som
tokenfri reserv. Spelarmarknader, halvleksspel, hörnor och kort rättas
manuellt i appen (auto-rättningen gäller bara fulltidsresultatet).

## Secrets

| Secret | Vad | Krävs |
|---|---|---|
| `FCM_SERVICE_ACCOUNT` | Firebase service-account-JSON för push-notisen | För push |
| `FOOTBALLDATA_TOKEN` | Gratis token från football-data.org | Rekommenderad |

## Köra lokalt

```bash
python3 scripts/generate.py     # bara standardbiblioteket, Python 3.9+
cat data/feed.json | python3 -m json.tool | head
```

## Disclaimer

Innehållet är redaktionell analys i informationssyfte. Odds är indikativa och
måste verifieras hos Svenska Spel innan spel. En modell ger sannolikheter,
inte profetior. 18+, Stödlinjen 020-81 91 00.
