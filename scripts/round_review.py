#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-omgångs slutspelsöversyn (deterministisk, körs av GitHub Actions).

Detekterar om en slutspelsomgång (R32/R16/kvart/semi/final) precis blivit
färdigspelad. Om så: kör kalibrering (modell vs facit) + CLV/skugg-P&L och
skriver en rapport till data/reviews/<omgång>.md (idempotent — en gång per
omgång), samt en sammanfattning till GitHub Actions-körningens summary.

VIKTIGT: detta gör INGA modell-/strategiändringar. Sådana kräver omdöme
(principiell signal, ej overfit) och görs av Claude-cykeln (det lokala
schemalagda tasket eller manuellt) — rapporten är UNDERLAGET + larmet som
talar om när en djup granskning är motiverad och om någon data-grind passerats.

Kör:  python3 scripts/round_review.py            (skriver rapport om ny omgång klar)
      python3 scripts/round_review.py --selftest (nätfri logiktest)
Bara standardbiblioteket (+ wc_model/wc_data via calibration_harness).
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
FEED = os.path.join(ROOT, "data", "feed.json")
REVIEWS_DIR = os.path.join(ROOT, "data", "reviews")
sys.path.insert(0, SCRIPTS)

# Slutspelsomgångar i ordning + förväntat antal matcher (48-lagsformatet).
KO_ROUNDS = [("Sextondelsfinal", 16), ("Åttondelsfinal", 8),
             ("Kvartsfinal", 4), ("Semifinal", 2), ("Final", 1)]


def latest_complete_round(results):
    """(omgångsnamn|None, {omgång: spelade}). En omgång är klar när antalet
    spelade matcher når det förväntade. Returnerar den DJUPASTE klara omgången."""
    from wc_data import stage_for
    played = {}
    for r in results or []:
        if r.get("scoreHome") is None or r.get("scoreAway") is None:
            continue
        st = stage_for(r.get("home"), r.get("away"), r.get("date"))
        played[st] = played.get(st, 0) + 1
    latest = None
    for name, exp in KO_ROUNDS:
        if played.get(name, 0) >= exp:
            latest = name
    return latest, played


def _fmt_calib(ko):
    if not ko:
        return "Ingen slutspelsdata att kalibrera än.\n"
    g = ko["goals"]
    over = ", ".join("%s %+.1f" % (x["team"], x["net"]) for x in ko["overperformers"][:5])
    under = ", ".join("%s %+.1f" % (x["team"], x["net"]) for x in ko["underperformers"][:5])
    sc = ", ".join("%s (%d)" % (x["name"], x["goals"]) for x in ko["top_scorers"][:6])
    return (
        "- Matcher (slutspel hittills): **%d**\n"
        "- Mål/match: faktiskt **%.2f** vs modell **%.2f** (hemma %.2f / borta %.2f)\n"
        "- Oavgjort %.0f%% · BTTS %.0f%% · Över 2.5 %.0f%% · Brier(1X2) **%.4f**\n"
        "- Överpresterare (mål vs väntat): %s\n"
        "- Underpresterare: %s\n"
        "- Toppskyttar: %s\n"
        % (ko["matches"], g["actual_avg"], g["model_exp_avg"], g["home_avg"],
           g["away_avg"], g["draw_pct"]*100, g["btts_pct"]*100, g["over25_pct"]*100,
           ko["brier_1x2"], over or "–", under or "–", sc or "–"))


def build_report(rnd, played, ko, clv_text):
    played_line = " · ".join("%s %d/%d" % (n, played.get(n, 0), e) for n, e in KO_ROUNDS)
    return (
        "# Slutspelsöversyn — %s\n\n"
        "_Automatisk deterministisk översyn (GitHub Actions). Gör inga modell-\n"
        "ändringar — underlag för den principiella Claude-cykeln._\n\n"
        "**Omgångsstatus:** %s\n\n"
        "## Kalibrering (modell vs facit, slutspel)\n%s\n"
        "## CLV & skugg-P&L\n```\n%s\n```\n"
        "## Grindar (data-gated)\n"
        "- **KO-1X2-policy:** aktivera bara om oavgjort-pickens KO-CLV > +1,5 %% på "
        "n ≥ 12 OCH KO-X skugg-P&L ROI ≥ 0 (se ”KO-fas” ovan).\n"
        "- **ADVANCE-marknad:** följ upp CLV/utfall när n växer; justera bara på robust signal.\n\n"
        "## Rekommendation\n"
        "→ **Kör den djupa granskningscykeln** (Claude: lokalt schemalagt task eller "
        "manuellt) för principiella förbättringar. Default = håll om signalen är svag/"
        "för litet sample. Överfit mot enskild omgång är förbjudet.\n"
        % (rnd, played_line, _fmt_calib(ko), clv_text.strip() or "(ingen CLV-data)"))


def _summary(text):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass


def main():
    results = json.load(open(FEED, encoding="utf-8")).get("results", [])
    rnd, played = latest_complete_round(results)
    if not rnd:
        msg = "Ingen avslutad slutspelsomgång än — håller. (status: %s)" % (
            " · ".join("%s %d/%d" % (n, played.get(n, 0), e) for n, e in KO_ROUNDS))
        print(msg); _summary("### Slutspelsöversyn\n" + msg)
        return 0
    os.makedirs(REVIEWS_DIR, exist_ok=True)
    report_path = os.path.join(REVIEWS_DIR, rnd.lower().replace(" ", "_") + ".md")
    if os.path.exists(report_path):
        msg = "Omgången **%s** redan granskad (%s finns) — håller." % (rnd, os.path.basename(report_path))
        print(msg); _summary("### Slutspelsöversyn\n" + msg)
        return 0

    # Kalibrering (fas-medveten, slutspel) via harnessen.
    try:
        import calibration_harness as cal
        from wc_model import build_ratings, KO_MSS_BLEND
        ratings, _m, _src = build_ratings()
        ratings_ko, _m2, _s2 = build_ratings(blend=KO_MSS_BLEND)
        ko = cal.analyze(results, ratings, ratings_ko, "ko")
    except Exception as e:
        print("  ! kalibrering failade: %s" % e, file=sys.stderr); ko = None
    # CLV-rapport (separat process — clv_report kör vid import).
    try:
        clv_text = subprocess.run([sys.executable, os.path.join(SCRIPTS, "clv_report.py")],
                                  capture_output=True, text=True, timeout=120).stdout
    except Exception as e:
        clv_text = "(clv_report failade: %s)" % e

    report = build_report(rnd, played, ko, clv_text)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("NY RAPPORT: %s" % report_path)
    _summary(report)
    return 0


def _selftest():
    print("round_review.py självtest ...")
    from wc_data import TEAMS
    # Bygg syntetiska resultat: full R32 (16) men ofullständig R16 (3) → senaste
    # KLARA omgång = Sextondelsfinal.
    shorts = [t[1] for t in TEAMS]
    res = []
    for i in range(16):  # 16 R32-matcher 2026-06-30 (Sextondelsfinal-fönstret)
        res.append({"home": shorts[i], "away": shorts[i + 16], "date": "2026-06-30",
                    "scoreHome": 2, "scoreAway": 0})
    for i in range(3):   # bara 3 R16-matcher (av 8) 2026-07-05 → ej klar
        res.append({"home": shorts[i], "away": shorts[i + 4], "date": "2026-07-05",
                    "scoreHome": 1, "scoreAway": 0})
    rnd, played = latest_complete_round(res)
    assert rnd == "Sextondelsfinal", (rnd, played)
    # Lägg resterande R16 → senaste klara blir Åttondelsfinal.
    for i in range(3, 8):
        res.append({"home": shorts[i + 8], "away": shorts[i + 12], "date": "2026-07-05",
                    "scoreHome": 1, "scoreAway": 0})
    rnd2, _ = latest_complete_round(res)
    assert rnd2 == "Åttondelsfinal", rnd2
    # Inga slutspelsmatcher → None.
    assert latest_complete_round([])[0] is None
    # Bara gruppspel → None.
    grp = [{"home": shorts[0], "away": shorts[1], "date": "2026-06-15",
            "scoreHome": 1, "scoreAway": 1}]
    assert latest_complete_round(grp)[0] is None
    print("  OK: R32-klar→%s, R16-klar→%s, tom→None" % (rnd, rnd2))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit(main())
