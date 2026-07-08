# Slutspelsöversyn — Åttondelsfinal

_Automatisk deterministisk översyn (GitHub Actions). Gör inga modell-
ändringar — underlag för den principiella Claude-cykeln._

**Omgångsstatus:** Sextondelsfinal 17/16 · Åttondelsfinal 9/8 · Kvartsfinal 0/4 · Semifinal 0/2 · Final 0/1

## Kalibrering (modell vs facit, slutspel)
- Matcher (slutspel hittills): **26**
- Mål/match: faktiskt **2.73** vs modell **2.50** (hemma 1.42 / borta 1.31)
- Oavgjort 27% · BTTS 58% · Över 2.5 54% · Brier(1X2) **0.1500**
- Överpresterare (mål vs väntat): Marocko +2.8, Kap Verde +2.2, Belgien +2.2, Spanien +1.9, Schweiz +1.4
- Underpresterare: Argentina -3.1, Kanada -2.5, Österrike -1.9, Ecuador -1.6, Sverige -1.5
- Toppskyttar: Erling Haaland (3), Kylian Mbappé (3), Harry Kane (2), Youri Tielemans (2), Mikel Oyarzabal (2), Lionel Messi (2)

## CLV & skugg-P&L
```
=== CLV (recOdds/closeOdds−1) — positivt = slår stängningslinjen ===
  recommendable=True   n=486  snitt-CLV -0.77%
  recommendable=False  n=988  snitt-CLV +0.02%

  per marknad (alla faser):
   PLAYER     n=349  CLV +1.27%
   CORNERS    n=104  CLV +0.81%
   1X2        n= 79  CLV +0.35%
   DC         n= 74  CLV +0.07%
   AH         n= 78  CLV -0.07%
   CARDS      n=178  CLV -0.52%
   ADVANCE    n= 26  CLV -0.71%
   TEAM_OU    n=101  CLV -0.91%
   1H_OU      n= 56  CLV -1.24%
   HTFT       n= 77  CLV -1.38%
   BTTS       n= 67  CLV -1.39%
   OU         n= 63  CLV -1.41%
   1H_1X2     n= 67  CLV -1.45%
   CS         n=155  CLV -1.61%

  KO-fas hittills (slutspel):
   CORNERS    n= 51  CLV +2.70%
   PLAYER     n=143  CLV +2.19%
   DC         n= 31  CLV +0.11%
   CARDS      n= 78  CLV -0.14%
   TEAM_OU    n= 52  CLV -0.55%
   ADVANCE    n= 26  CLV -0.71%
   AH         n= 31  CLV -0.88%
   BTTS       n= 30  CLV -0.89%
   1H_OU      n= 29  CLV -0.94%
   1H_1X2     n= 31  CLV -1.16%
   1X2        n= 32  CLV -1.16%
   CS         n= 79  CLV -1.70%
   HTFT       n= 29  CLV -1.91%
   OU         n= 27  CLV -2.29%
   1X2 (X)    n=  7  CLV -0.89%  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate: aktivera bara om CLV>+1.5% & n>=12 & ROI>=0)

=== Skugg-P&L (platt 1 enhet) — rekommenderade vs ej ===
  recommendable=True   486 rättade  246 vinst  ROI   -7.3%  resultat  -35.6
  recommendable=False  545 rättade  70 vinst  ROI  -30.2%  resultat -164.4

  per marknad (settlad P&L):
   PLAYER     188 rättade  20 vinst  ROI  -40.2%  resultat  -75.6
   CS         155 rättade  12 vinst  ROI  -25.5%  resultat  -39.5
   HTFT        77 rättade  11 vinst  ROI  -44.9%  resultat  -34.6
   1X2         79 rättade  19 vinst  ROI  -21.1%  resultat  -16.6
   TEAM_OU    101 rättade  48 vinst  ROI  -11.6%  resultat  -11.7
   DC          74 rättade  38 vinst  ROI  -14.6%  resultat  -10.8
   1H_OU       56 rättade  30 vinst  ROI  -12.9%  resultat   -7.2
   OU          63 rättade  28 vinst  ROI  -10.9%  resultat   -6.9
   BTTS        67 rättade  32 vinst  ROI   -6.3%  resultat   -4.2
   AH          78 rättade  42 vinst  ROI   -1.5%  resultat   -1.2
   ADVANCE     26 rättade  13 vinst  ROI   -2.0%  resultat   -0.5
   1H_1X2      67 rättade  23 vinst  ROI  +13.2%  resultat   +8.8

  KO-fas settlad P&L (slutspel):
   PLAYER      79 rättade   8 vinst  ROI  -54.4%  resultat  -43.0
   CS          79 rättade   7 vinst  ROI  -31.6%  resultat  -25.0
   HTFT        29 rättade   5 vinst  ROI  -42.1%  resultat  -12.2
   DC          31 rättade  17 vinst  ROI  -18.1%  resultat   -5.6
   TEAM_OU     52 rättade  26 vinst  ROI   -8.6%  resultat   -4.5
   1X2         32 rättade   9 vinst  ROI  -11.9%  resultat   -3.8
   BTTS        30 rättade  14 vinst  ROI   -7.3%  resultat   -2.2
   1H_OU       29 rättade  17 vinst  ROI   -6.6%  resultat   -1.9
   AH          31 rättade  16 vinst  ROI   -2.9%  resultat   -0.9
   ADVANCE     26 rättade  13 vinst  ROI   -2.0%  resultat   -0.5
   OU          27 rättade  14 vinst  ROI   +2.9%  resultat   +0.8
   1H_1X2      31 rättade  12 vinst  ROI  +26.6%  resultat   +8.2
   1X2 (X)      7 rättade   1 vinst  ROI  +35.7%  resultat   +2.5  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate)
```
## Grindar (data-gated)
- **KO-1X2-policy:** aktivera bara om oavgjort-pickens KO-CLV > +1,5 % på n ≥ 12 OCH KO-X skugg-P&L ROI ≥ 0 (se ”KO-fas” ovan).
- **ADVANCE-marknad:** följ upp CLV/utfall när n växer; justera bara på robust signal.

## Rekommendation
→ **Kör den djupa granskningscykeln** (Claude: lokalt schemalagt task eller manuellt) för principiella förbättringar. Default = håll om signalen är svag/för litet sample. Överfit mot enskild omgång är förbjudet.
