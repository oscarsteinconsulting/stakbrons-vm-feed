#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Målgörarmodell (anytime-skytt) — REN ANALYS, rekommenderas aldrig.

Marknaden för målgörare är skarp och vi saknar full trupp-/speltidsdata, så
detta används bara för att VISA en modellbaserad skytteanalys per slutspels-
match i appen — aldrig för att staka spel (inget Kelly, ingen edge-rekommendation).

Metod (Poisson, samma λ som matchmodellen):
  λ_spelare = lag_λ · spelarandel · rollfaktor
  spelarandel = empirisk-Bayes: (mål + K·baslinje)/(lagets mål + K), så att
    spelare med få mål dras kraftigt mot lagbaslinjen (anti-overfit på n=1–2).
  P(gör mål)   = 1 − e^(−λ_spelare)
  P(2+ mål)    = 1 − e^(−λ) − λ·e^(−λ)

Begränsning (medveten): bara spelare som faktiskt gjort mål i turneringen får
en rad — vi har ingen gratis trupp-/startelvakälla för VM 2026. En anfallare
som inte målat i gruppspelet syns alltså inte. Det är ärligt för en ren
"vem har målformen"-analys; trupp-/positionsberikning är en framtida förbättring.

Bara standardbiblioteket. Python 3.9+.
"""
import math

K_SHRINK = 6.0        # pseudomål mot baslinjeandelen (dämpar litet sample)
N_OUTFIELD = 18       # ~utespelare som kan göra mål → baslinjeandel 1/18
ROLE_DEFAULT = 1.0    # ingen positionsdata → neutral roll (källan är ju skyttar)
MIN_TEAM_GOALS = 2    # lag måste ha gjort minst så många mål för en andel
TOP_N = 6


def team_goal_table(results):
    """{lag: {spelare: mål}}, {lag: totalmål} ur resultatens scorers-listor.

    Aggregerar över alla matcher i facit. Self-/straffmål räknas som de står i
    källan (vi särskiljer dem inte)."""
    by_team, totals = {}, {}
    for r in results or []:
        for s in (r.get("scorers") or []):
            t, name = s.get("team"), s.get("name")
            g = s.get("goals", 0) or 0
            if not t or not name or g <= 0:
                continue
            tbl = by_team.setdefault(t, {})
            tbl[name] = tbl.get(name, 0) + g
            totals[t] = totals.get(t, 0) + g
    return by_team, totals


def player_share(goals, team_total, k=K_SHRINK, n_outfield=N_OUTFIELD):
    """Empirisk-Bayes-andel av lagets mål: krymper mot 1/n_outfield."""
    base = 1.0 / n_outfield
    denom = team_total + k
    return (goals + k * base) / denom if denom > 0 else base


def scorer_probs(lam_team, share, role=ROLE_DEFAULT):
    """(λ_spelare, P(anytime), P(2+)) ur Poisson."""
    lam_p = max(0.0, lam_team * share * role)
    e = math.exp(-lam_p)
    p1 = 1.0 - e
    p2 = 1.0 - e - lam_p * e
    return lam_p, max(0.0, p1), max(0.0, p2)


def match_scorer_analysis(home, away, lam_home, lam_away, by_team, totals,
                          top_n=TOP_N):
    """Topp-N anytime-kandidater för en match (sorterat på P(anytime)).

    Returnerar en lista av dicts: player/team/groupGoals/lambda/pAnytime/p2plus.
    Tom lista om inget lag har tillräckligt med måldata."""
    rows = []
    for team, lam in ((home, lam_home), (away, lam_away)):
        tot = totals.get(team, 0)
        if tot < MIN_TEAM_GOALS:
            continue
        for name, g in by_team.get(team, {}).items():
            share = player_share(g, tot)
            lam_p, p1, p2 = scorer_probs(lam, share)
            rows.append({
                "player": name, "team": team, "groupGoals": g,
                "lambda": round(lam_p, 3),
                "pAnytime": round(p1, 3), "p2plus": round(p2, 3),
            })
    rows.sort(key=lambda x: -x["pAnytime"])
    return rows[:top_n]


# ---------------------------------------------------------------------------
def _selftest():
    print("scorer_model.py självtest ...")
    results = [
        {"home": "Frankrike", "away": "X", "scorers": [
            {"team": "Frankrike", "name": "Mbappé", "goals": 3},
            {"team": "Frankrike", "name": "Dembélé", "goals": 2}]},
        {"home": "Frankrike", "away": "Y", "scorers": [
            {"team": "Frankrike", "name": "Mbappé", "goals": 1},
            {"team": "Frankrike", "name": "Kolo Muani", "goals": 1}]},
    ]
    by_team, totals = team_goal_table(results)
    assert totals["Frankrike"] == 7, totals
    assert by_team["Frankrike"]["Mbappé"] == 4, by_team
    # andelar summerar inte till 1 (shrink mot baslinje) men är monotona
    s_mbappe = player_share(4, 7)
    s_kolo = player_share(1, 7)
    assert s_mbappe > s_kolo > 0, (s_mbappe, s_kolo)
    assert s_mbappe < 4 / 7, "shrink ska dra ned toppskyttens råandel"
    lam_p, p1, p2 = scorer_probs(1.8, s_mbappe)
    assert 0 < p2 < p1 < 1, (p1, p2)
    rows = match_scorer_analysis("Frankrike", "Z", 1.8, 0.8, by_team, totals)
    assert rows and rows[0]["player"] == "Mbappé", rows
    assert all(r["pAnytime"] >= rows[-1]["pAnytime"] for r in rows), "ej sorterad"
    # lag utan måldata → ingen rad
    assert all(r["team"] == "Frankrike" for r in rows), rows
    print("  OK: %d kandidater, Mbappé P(anytime)=%.3f P(2+)=%.3f"
          % (len(rows), rows[0]["pAnytime"], rows[0]["p2plus"]))


if __name__ == "__main__":
    _selftest()
