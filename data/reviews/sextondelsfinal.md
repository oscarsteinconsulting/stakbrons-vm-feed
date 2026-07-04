# Slutspelsöversyn — Sextondelsfinal

_Automatisk deterministisk översyn (GitHub Actions). Gör inga modell-
ändringar — underlag för den principiella Claude-cykeln._

**Omgångsstatus:** Sextondelsfinal 17/16 · Åttondelsfinal 1/8 · Kvartsfinal 0/4 · Semifinal 0/2 · Final 0/1

## Kalibrering (modell vs facit, slutspel)
- Matcher (slutspel hittills): **18**
- Mål/match: faktiskt **2.67** vs modell **2.50** (hemma 1.67 / borta 1.00)
- Oavgjort 33% · BTTS 61% · Över 2.5 50% · Brier(1X2) **0.1709**
- Överpresterare (mål vs väntat): Kap Verde +2.1, Frankrike +2.0, Mexiko +2.0, Spanien +1.8, Schweiz +1.5
- Underpresterare: Sverige -2.0, Ecuador -2.0, Österrike -2.0, Argentina -2.0, Bosnien -1.3
- Toppskyttar: Kylian Mbappé (2), Harry Kane (2), Youri Tielemans (2), Mikel Oyarzabal (2), Stephen Eustáquio (1), Kaishu Sano (1)

## CLV & skugg-P&L
```
=== CLV (recOdds/closeOdds−1) — positivt = slår stängningslinjen ===
  recommendable=True   n=435  snitt-CLV -0.96%
  recommendable=False  n=887  snitt-CLV -0.07%

  per marknad (alla faser):
   PLAYER     n=315  CLV +1.44%
   CORNERS    n= 92  CLV +0.27%
   1X2        n= 73  CLV +0.22%
   DC         n= 65  CLV -0.11%
   AH         n= 72  CLV -0.21%
   CARDS      n=158  CLV -0.61%
   TEAM_OU    n= 90  CLV -1.11%
   ADVANCE    n= 20  CLV -1.26%
   HTFT       n= 69  CLV -1.44%
   BTTS       n= 61  CLV -1.48%
   1H_OU      n= 50  CLV -1.63%
   OU         n= 57  CLV -1.63%
   1H_1X2     n= 60  CLV -1.68%
   CS         n=140  CLV -1.88%

  KO-fas hittills (slutspel):
   PLAYER     n=109  CLV +2.98%
   CORNERS    n= 39  CLV +2.00%
   CARDS      n= 58  CLV -0.27%
   DC         n= 22  CLV -0.40%
   TEAM_OU    n= 41  CLV -0.90%
   BTTS       n= 24  CLV -0.97%
   ADVANCE    n= 20  CLV -1.26%
   AH         n= 25  CLV -1.49%
   1H_1X2     n= 24  CLV -1.64%
   1H_OU      n= 23  CLV -1.70%
   1X2        n= 26  CLV -1.90%
   HTFT       n= 21  CLV -2.32%
   CS         n= 64  CLV -2.33%
   OU         n= 21  CLV -3.14%
   1X2 (X)    n=  6  CLV -1.51%  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate: aktivera bara om CLV>+1.5% & n>=12 & ROI>=0)

=== Skugg-P&L (platt 1 enhet) — rekommenderade vs ej ===
  recommendable=True   419 rättade  207 vinst  ROI   -9.4%  resultat  -39.5
  recommendable=False  473 rättade  59 vinst  ROI  -28.7%  resultat -136.0

  per marknad (settlad P&L):
   PLAYER     164 rättade  20 vinst  ROI  -31.5%  resultat  -51.6
   CS         135 rättade  10 vinst  ROI  -25.4%  resultat  -34.2
   HTFT        67 rättade   9 vinst  ROI  -49.0%  resultat  -32.8
   1X2         70 rättade  15 vinst  ROI  -27.2%  resultat  -19.0
   TEAM_OU     86 rättade  39 vinst  ROI  -16.0%  resultat  -13.8
   DC          63 rättade  31 vinst  ROI  -15.8%  resultat  -10.0
   OU          55 rättade  24 vinst  ROI  -14.3%  resultat   -7.9
   1H_OU       48 rättade  26 vinst  ROI  -10.7%  resultat   -5.1
   ADVANCE     18 rättade   7 vinst  ROI  -22.6%  resultat   -4.1
   AH          69 rättade  36 vinst  ROI   -5.5%  resultat   -3.8
   BTTS        59 rättade  30 vinst  ROI   -0.7%  resultat   -0.4
   1H_1X2      58 rättade  19 vinst  ROI  +12.6%  resultat   +7.3

  KO-fas settlad P&L (slutspel):
   CS          59 rättade   5 vinst  ROI  -33.5%  resultat  -19.8
   PLAYER      55 rättade   8 vinst  ROI  -34.5%  resultat  -18.9
   HTFT        19 rättade   3 vinst  ROI  -55.0%  resultat  -10.5
   TEAM_OU     37 rättade  17 vinst  ROI  -17.7%  resultat   -6.5
   1X2         23 rättade   5 vinst  ROI  -26.9%  resultat   -6.2
   DC          20 rättade  10 vinst  ROI  -23.7%  resultat   -4.7
   ADVANCE     18 rättade   7 vinst  ROI  -22.6%  resultat   -4.1
   AH          22 rättade  10 vinst  ROI  -16.0%  resultat   -3.5
   OU          19 rättade  10 vinst  ROI   -1.3%  resultat   -0.2
   1H_OU       21 rättade  13 vinst  ROI   +0.8%  resultat   +0.2
   BTTS        22 rättade  12 vinst  ROI   +7.3%  resultat   +1.6
   1H_1X2      22 rättade   8 vinst  ROI  +30.5%  resultat   +6.7
   1X2 (X)      5 rättade   1 vinst  ROI  +90.0%  resultat   +4.5  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate)
```
## Grindar (data-gated)
- **KO-1X2-policy:** aktivera bara om oavgjort-pickens KO-CLV > +1,5 % på n ≥ 12 OCH KO-X skugg-P&L ROI ≥ 0 (se ”KO-fas” ovan).
- **ADVANCE-marknad:** följ upp CLV/utfall när n växer; justera bara på robust signal.

## Rekommendation
→ **Kör den djupa granskningscykeln** (Claude: lokalt schemalagt task eller manuellt) för principiella förbättringar. Default = håll om signalen är svag/för litet sample. Överfit mot enskild omgång är förbjudet.
