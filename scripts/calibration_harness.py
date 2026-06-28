#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kalibrerings-harness: modellens prediktioner vs facit, per fas.

Återskapar modellens λ / 1X2 / förväntade mål för varje spelad match i
data/feed.json:results och jämför mot utfallen — uppdelat på gruppspel resp.
slutspel (fas-medveten μ, samma val som generate.py). Rapporterar mål-nivå,
Brier(1X2) + reliabilitet, lagens över/underprestation (mål vs förväntat) och
målgörarkoncentration. Driver den periodiska slutspelsöversynen.

Kör:  python3 scripts/calibration_harness.py            (rapport till stdout)
      python3 scripts/calibration_harness.py --json out.json   (+ JSON-dump)
      python3 scripts/calibration_harness.py --stage ko        (bara slutspel)

Bara standardbiblioteket (+ wc_model/wc_data). Python 3.9+.
"""
import json
import math
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wc_model import MatchModel, build_ratings, MU_TOTAL, KO_MU_TOTAL, KO_MSS_BLEND
from wc_data import GROUP_OF, stage_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(ROOT, "data", "feed.json")


def is_knockout(stage):
    return bool(stage) and stage != "Gruppspel" and not stage.startswith("Grupp")


def analyze(results, ratings, ratings_ko, want_stage=None):
    """Kalibreringsmått över de spelade matcherna (filtrerat på fas om angivet)."""
    tot, homeg, awayg = [], [], []
    brier = 0.0; n = 0
    exp_tot = []
    bins = defaultdict(lambda: [0, 0])           # prob-bin → [hits, n]
    gf_exp = defaultdict(float); gf_act = defaultdict(float)
    ga_exp = defaultdict(float); ga_act = defaultdict(float)
    draws = btts = over25 = 0
    sc = defaultdict(int)
    used = 0

    for r in results:
        h, a = r.get("home"), r.get("away")
        sh, sa = r.get("scoreHome"), r.get("scoreAway")
        if h not in ratings or a not in ratings or sh is None or sa is None:
            continue
        stage = stage_for(h, a, r.get("date"))
        ko = is_knockout(stage)
        if want_stage == "group" and ko:
            continue
        if want_stage == "ko" and not ko:
            continue
        mu = KO_MU_TOTAL if ko else MU_TOTAL
        m = MatchModel(h, a, ratings_ko if ko else ratings, mu_total=mu)
        ph, pd, pa = m.p_1x2()
        used += 1
        tot.append(sh + sa); homeg.append(sh); awayg.append(sa)
        exp_tot.append(m.lam_h + m.lam_a)
        draws += 1 if sh == sa else 0
        btts += 1 if (sh >= 1 and sa >= 1) else 0
        over25 += 1 if sh + sa > 2.5 else 0
        gf_exp[h] += m.lam_h; ga_exp[h] += m.lam_a
        gf_exp[a] += m.lam_a; ga_exp[a] += m.lam_h
        gf_act[h] += sh; ga_act[h] += sa
        gf_act[a] += sa; ga_act[a] += sh
        out = "1" if sh > sa else ("2" if sh < sa else "X")
        for sign, p in (("1", ph), ("X", pd), ("2", pa)):
            brier += (p - (1.0 if sign == out else 0.0)) ** 2
            b = min(int(p * 10), 9); bins[b][1] += 1; bins[b][0] += 1 if sign == out else 0
        n += 1
        for s in (r.get("scorers") or []):
            sc[(s.get("team"), s.get("name"))] += s.get("goals", 0) or 0

    if not used:
        return None
    net = [(t, (gf_act[t] - gf_exp[t]) - (ga_act[t] - ga_exp[t])) for t in gf_act]
    net.sort(key=lambda x: -x[1])
    return {
        "matches": used,
        "goals": {"actual_avg": sum(tot) / len(tot), "model_exp_avg": sum(exp_tot) / len(exp_tot),
                  "home_avg": sum(homeg) / len(homeg), "away_avg": sum(awayg) / len(awayg),
                  "draw_pct": draws / used, "btts_pct": btts / used, "over25_pct": over25 / used},
        "brier_1x2": brier / (n * 3),
        "reliability": {b: {"hits": bins[b][0], "n": bins[b][1]} for b in range(10) if bins[b][1]},
        "overperformers": [{"team": t, "net": round(v, 2)} for t, v in net[:6]],
        "underperformers": [{"team": t, "net": round(v, 2)} for t, v in net[-6:][::-1]],
        "top_scorers": [{"name": k[1], "team": k[0], "goals": v}
                        for k, v in sorted(sc.items(), key=lambda x: -x[1])[:10]],
    }


def _print(title, a):
    if a is None:
        print("\n=== %s: inga spelade matcher ===" % title); return
    g = a["goals"]
    print("\n=== %s (%d matcher) ===" % (title, a["matches"]))
    print("  mål/match faktiskt %.2f vs modell %.2f | hemma %.2f borta %.2f"
          % (g["actual_avg"], g["model_exp_avg"], g["home_avg"], g["away_avg"]))
    print("  oavgjort %.0f%% | BTTS %.0f%% | Över2.5 %.0f%% | Brier(1X2) %.4f"
          % (g["draw_pct"]*100, g["btts_pct"]*100, g["over25_pct"]*100, a["brier_1x2"]))
    print("  överpresterare:", [(x["team"], x["net"]) for x in a["overperformers"][:4]])
    print("  underpresterare:", [(x["team"], x["net"]) for x in a["underperformers"][:4]])
    print("  toppskyttar:", [(x["name"], x["goals"]) for x in a["top_scorers"][:6]])


def main(argv):
    want = None
    if "--stage" in argv:
        want = argv[argv.index("--stage") + 1]
    results = json.load(open(FEED))["results"]
    ratings, _mss, src = build_ratings()
    ratings_ko, _, _ = build_ratings(blend=KO_MSS_BLEND)
    print("Elo-källa: %s | results i facit: %d | MU grupp/KO %.2f/%.2f"
          % (src, len(results), MU_TOTAL, KO_MU_TOTAL))
    report = {}
    if want in (None, "group"):
        report["group"] = analyze(results, ratings, ratings_ko, "group"); _print("GRUPPSPEL", report["group"])
    if want in (None, "ko"):
        report["ko"] = analyze(results, ratings, ratings_ko, "ko"); _print("SLUTSPEL", report["ko"])
    if "--json" in argv:
        path = argv[argv.index("--json") + 1]
        json.dump(report, open(path, "w"), ensure_ascii=False, indent=1)
        print("\n[skrev %s]" % path)


if __name__ == "__main__":
    main(sys.argv[1:])
