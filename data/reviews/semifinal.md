# Slutspelsöversyn — Semifinal

_Automatisk deterministisk översyn (GitHub Actions). Gör inga modell-
ändringar — underlag för den principiella Claude-cykeln._

**Omgångsstatus:** Sextondelsfinal 17/16 · Åttondelsfinal 9/8 · Kvartsfinal 3/4 · Semifinal 2/2 · Final 0/1

## Kalibrering (modell vs facit, slutspel)
- Matcher (slutspel hittills): **31**
- Mål/match: faktiskt **2.65** vs modell **2.50** (hemma 1.39 / borta 1.26)
- Oavgjort 29% · BTTS 58% · Över 2.5 48% · Brier(1X2) **0.1544**
- Överpresterare (mål vs väntat): Spanien +3.0, Schweiz +2.5, Belgien +2.4, Kap Verde +2.2, Norge +2.0
- Underpresterare: Argentina -4.1, Kanada -2.6, Österrike -1.7, Ecuador -1.6, Sverige -1.5
- Toppskyttar: Kylian Mbappé (4), Erling Haaland (3), Mikel Oyarzabal (3), Harry Kane (2), Youri Tielemans (2), Pedro Porro (2)

## CLV & skugg-P&L
```
=== CLV (recOdds/closeOdds−1) — positivt = slår stängningslinjen ===
  recommendable=True   n=545  snitt-CLV -0.71%
  recommendable=False  n=1086  snitt-CLV -0.08%

  per marknad (alla faser):
   PLAYER     n=379  CLV +0.98%
   CORNERS    n=115  CLV +0.77%
   1X2        n= 86  CLV +0.16%
   DC         n= 82  CLV +0.05%
   AH         n= 86  CLV -0.04%
   CARDS      n=196  CLV -0.42%
   ADVANCE    n= 33  CLV -0.78%
   TEAM_OU    n=115  CLV -0.85%
   1H_OU      n= 66  CLV -0.95%
   1H_1X2     n= 75  CLV -1.21%
   OU         n= 69  CLV -1.30%
   BTTS       n= 73  CLV -1.31%
   HTFT       n= 85  CLV -1.46%
   CS         n=171  CLV -1.61%

  KO-fas hittills (slutspel):
   CORNERS    n= 62  CLV +2.28%
   PLAYER     n=173  CLV +1.40%
   DC         n= 39  CLV +0.06%
   CARDS      n= 96  CLV -0.02%
   TEAM_OU    n= 66  CLV -0.52%
   1H_OU      n= 39  CLV -0.53%
   AH         n= 39  CLV -0.64%
   1H_1X2     n= 39  CLV -0.76%
   ADVANCE    n= 33  CLV -0.78%
   BTTS       n= 36  CLV -0.80%
   1X2        n= 39  CLV -1.32%
   CS         n= 95  CLV -1.69%
   OU         n= 33  CLV -1.89%
   HTFT       n= 37  CLV -1.98%
   1X2 (X)    n=  9  CLV -1.39%  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate: aktivera bara om CLV>+1.5% & n>=12 & ROI>=0)

=== Skugg-P&L (platt 1 enhet) — rekommenderade vs ej ===
  recommendable=True   537 rättade  272 vinst  ROI   -7.1%  resultat  -38.3
  recommendable=False  599 rättade  84 vinst  ROI  -24.1%  resultat -144.3

  per marknad (settlad P&L):
   PLAYER     208 rättade  22 vinst  ROI  -37.8%  resultat  -78.6
   HTFT        84 rättade  13 vinst  ROI  -37.1%  resultat  -31.2
   CS         169 rättade  15 vinst  ROI  -15.6%  resultat  -26.4
   1X2         85 rättade  21 vinst  ROI  -18.5%  resultat  -15.7
   TEAM_OU    113 rättade  54 vinst  ROI  -10.9%  resultat  -12.3
   DC          81 rättade  42 vinst  ROI  -13.6%  resultat  -11.0
   1H_OU       65 rättade  33 vinst  ROI  -16.1%  resultat  -10.5
   OU          68 rättade  31 vinst  ROI   -8.6%  resultat   -5.8
   BTTS        72 rättade  35 vinst  ROI   -4.1%  resultat   -3.0
   ADVANCE     32 rättade  16 vinst  ROI   -5.7%  resultat   -1.8
   AH          85 rättade  46 vinst  ROI   -1.0%  resultat   -0.8
   1H_1X2      74 rättade  28 vinst  ROI  +19.6%  resultat  +14.5

  KO-fas settlad P&L (slutspel):
   PLAYER      99 rättade  10 vinst  ROI  -46.4%  resultat  -46.0
   CS          93 rättade  10 vinst  ROI  -12.7%  resultat  -11.9
   HTFT        36 rättade   7 vinst  ROI  -24.4%  resultat   -8.8
   DC          38 rättade  21 vinst  ROI  -15.2%  resultat   -5.8
   1H_OU       38 rättade  20 vinst  ROI  -13.6%  resultat   -5.2
   TEAM_OU     64 rättade  32 vinst  ROI   -8.0%  resultat   -5.1
   1X2         38 rättade  11 vinst  ROI   -7.7%  resultat   -2.9
   ADVANCE     32 rättade  16 vinst  ROI   -5.7%  resultat   -1.8
   BTTS        35 rättade  17 vinst  ROI   -2.7%  resultat   -0.9
   AH          38 rättade  20 vinst  ROI   -1.4%  resultat   -0.5
   OU          32 rättade  17 vinst  ROI   +5.7%  resultat   +1.8
   1H_1X2      38 rättade  17 vinst  ROI  +36.7%  resultat  +13.9
   1X2 (X)      9 rättade   2 vinst  ROI  +47.2%  resultat   +4.2  [otillräckligt n — ej beslutsgrundande]   (KO-1X2-gate)
```
## Grindar (data-gated)
- **KO-1X2-policy:** aktivera bara om oavgjort-pickens KO-CLV > +1,5 % på n ≥ 12 OCH KO-X skugg-P&L ROI ≥ 0 (se ”KO-fas” ovan).
- **ADVANCE-marknad:** följ upp CLV/utfall när n växer; justera bara på robust signal.

## Rekommendation
→ **Kör den djupa granskningscykeln** (Claude: lokalt schemalagt task eller manuellt) för principiella förbättringar. Default = håll om signalen är svag/för litet sample. Överfit mot enskild omgång är förbjudet.
