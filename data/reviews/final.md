# Slutspelsöversyn — Final

_Automatisk deterministisk översyn (GitHub Actions). Gör inga modell-
ändringar — underlag för den principiella Claude-cykeln._

**Omgångsstatus:** Sextondelsfinal 17/16 · Åttondelsfinal 9/8 · Kvartsfinal 3/4 · Semifinal 3/2 · Final 1/1

## Kalibrering (modell vs facit, slutspel)
- Matcher (slutspel hittills): **34**
- Mål/match: faktiskt **2.79** vs modell **2.50** (hemma 1.41 / borta 1.38)
- Oavgjort 29% · BTTS 59% · Över 2.5 50% · Brier(1X2) **0.1585**
- Överpresterare (mål vs väntat): Belgien +2.5, Schweiz +2.5, Kap Verde +2.2, Spanien +2.2, Norge +2.0
- Underpresterare: Argentina -3.0, Kanada -2.6, Sverige -1.7, Ecuador -1.6, Österrike -1.6
- Toppskyttar: Kylian Mbappé (6), Erling Haaland (3), Mikel Oyarzabal (3), Jude Bellingham (3), Bukayo Saka (3), Bradley Barcola (2)

## CLV & skugg-P&L
```
=== CLV (recOdds/closeOdds−1) — positivt = slår stängningslinjen ===
  recommendable=True   n=560  snitt-CLV -0.75%
  recommendable=False  n=1123  snitt-CLV -0.11%

  per marknad (alla faser):
   PLAYER     n=393  CLV +0.98%
   CORNERS    n=120  CLV +0.75%
   1X2        n= 88  CLV -0.06%
   DC         n= 84  CLV -0.12%
   AH         n= 88  CLV -0.20%
   CARDS      n=200  CLV -0.41%
   TEAM_OU    n=120  CLV -0.81%
   ADVANCE    n= 33  CLV -0.84%
   1H_OU      n= 68  CLV -0.96%
   1H_1X2     n= 77  CLV -1.25%
   BTTS       n= 75  CLV -1.27%
   OU         n= 71  CLV -1.36%
   HTFT       n= 88  CLV -1.53%
   CS         n=178  CLV -1.66%

  KO-fas hittills (slutspel):
   CORNERS    n= 67  CLV +2.14%
   PLAYER     n=187  CLV +1.37%
   CARDS      n=100  CLV -0.00%
   DC         n= 41  CLV -0.28%
   TEAM_OU    n= 71  CLV -0.48%
   1H_OU      n= 41  CLV -0.56%
   BTTS       n= 38  CLV -0.75%
   ADVANCE    n= 33  CLV -0.84%
   1H_1X2     n= 41  CLV -0.85%
   AH         n= 41  CLV -0.95%
   1X2        n= 41  CLV -1.73%
   CS         n=102  CLV -1.78%
   OU         n= 35  CLV -1.99%
   HTFT       n= 40  CLV -2.11%
   1X2 (X)    n=  9  CLV -1.39%  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate: aktivera bara om CLV>+1.5% & n>=12 & ROI>=0)

=== Skugg-P&L (platt 1 enhet) — rekommenderade vs ej ===
  recommendable=True   560 rättade  284 vinst  ROI   -7.3%  resultat  -40.6
  recommendable=False  636 rättade  89 vinst  ROI  -24.1%  resultat -153.4

  per marknad (settlad P&L):
   PLAYER     226 rättade  23 vinst  ROI  -41.0%  resultat  -92.6
   HTFT        88 rättade  14 vinst  ROI  -32.3%  resultat  -28.4
   CS         178 rättade  16 vinst  ROI  -14.2%  resultat  -25.4
   TEAM_OU    120 rättade  57 vinst  ROI  -12.5%  resultat  -15.0
   1H_OU       68 rättade  33 vinst  ROI  -19.8%  resultat  -13.5
   1X2         88 rättade  23 vinst  ROI  -13.2%  resultat  -11.6
   DC          84 rättade  45 vinst  ROI  -10.7%  resultat   -9.0
   OU          71 rättade  32 vinst  ROI   -9.1%  resultat   -6.4
   BTTS        75 rättade  36 vinst  ROI   -5.4%  resultat   -4.0
   ADVANCE     33 rättade  17 vinst  ROI   -2.5%  resultat   -0.8
   AH          88 rättade  49 vinst  ROI   +1.4%  resultat   +1.3
   1H_1X2      77 rättade  28 vinst  ROI  +15.0%  resultat  +11.5

  KO-fas settlad P&L (slutspel):
   PLAYER     117 rättade  11 vinst  ROI  -51.2%  resultat  -60.0
   CS         102 rättade  11 vinst  ROI  -10.6%  resultat  -10.9
   1H_OU       41 rättade  20 vinst  ROI  -19.9%  resultat   -8.2
   TEAM_OU     71 rättade  35 vinst  ROI  -10.9%  resultat   -7.8
   HTFT        40 rättade   8 vinst  ROI  -15.1%  resultat   -6.1
   DC          41 rättade  24 vinst  ROI   -9.3%  resultat   -3.8
   BTTS        38 rättade  18 vinst  ROI   -5.3%  resultat   -2.0
   ADVANCE     33 rättade  17 vinst  ROI   -2.5%  resultat   -0.8
   1X2         41 rättade  13 vinst  ROI   +2.9%  resultat   +1.2
   OU          35 rättade  18 vinst  ROI   +3.5%  resultat   +1.2
   AH          41 rättade  23 vinst  ROI   +3.8%  resultat   +1.5
   1H_1X2      41 rättade  17 vinst  ROI  +26.7%  resultat  +10.9
   1X2 (X)      9 rättade   2 vinst  ROI  +47.2%  resultat   +4.2  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate)
```
## Grindar (data-gated)
- **KO-1X2-policy:** aktivera bara om oavgjort-pickens KO-CLV > +1,5 % på n ≥ 12 OCH KO-X skugg-P&L ROI ≥ 0 (se ”KO-fas” ovan).
- **ADVANCE-marknad:** följ upp CLV/utfall när n växer; justera bara på robust signal.

## Rekommendation
→ **Kör den djupa granskningscykeln** (Claude: lokalt schemalagt task eller manuellt) för principiella förbättringar. Default = håll om signalen är svag/för litet sample. Överfit mot enskild omgång är förbjudet.
