#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Målgörarmodell (anytime-skytt) — REN ANALYS, rekommenderas aldrig.

Marknaden för målgörare är skarp och vi saknar full speltidsdata, så detta
används bara för att VISA en modellbaserad skytteanalys per slutspelsmatch i
appen — aldrig för att staka spel (inget Kelly, ingen edge-rekommendation).

Metod (Poisson, samma λ som matchmodellen):
  λ_spelare = lag_λ · spelarandel
  spelarandel = empirisk-Bayes: (mål + K·prior)/(lagets mål + K), där prior =
    baslinje (1/N) · rollfaktor. Rollfaktorn (anfallare>mittfält>försvar) styr
    BARA shrink-målet för spelare utan/med få mål — en spelare som FAKTISKT
    målat domineras av sin egen måldata (rollen påverkar då försumbart). Så en
    mållös anfallare får högre baslinje-andel än en mållös försvarare, utan att
    en målande mittfältare straffas.
  P(gör mål)   = 1 − e^(−λ_spelare);  P(2+) = 1 − e^(−λ) − λ·e^(−λ)

Truppberikning (valfri): om en trupplista (squads) ges får även MÅLLÖSA spelare
en rad (med position/speltid), så en toppanfallare som ännu inte målat syns.
UTAN squads beter sig modulen EXAKT som scorers-only (bakåtkompatibelt).

Bara standardbiblioteket. Python 3.9+.
"""
import math

K_SHRINK = 6.0        # pseudomål mot prior (dämpar litet sample)
N_OUTFIELD = 18       # ~utespelare som kan göra mål → baslinje 1/18
ROLE_DEFAULT = 1.0    # roll okänd → neutral
MIN_TEAM_GOALS = 2    # lag måste ha mål ELLER trupp för en analys
TOP_N = 6

# Konservativa default-rollfaktorer (normaliserade mot anfallare=1.0). Härleds
# empiriskt ur facit när data räcker (se derive_role_factors); annars dessa.
ROLE_FACTOR = {"F": 1.0, "M": 0.45, "D": 0.12, "G": 0.01}


def team_goal_table(results):
    """{lag: {spelare: mål}}, {lag: totalmål} ur resultatens scorers-listor."""
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


def squad_table(squads):
    """{lag: {namn: {'pos','apps','injured'}}} ur fetch_espn_squads-utdata."""
    out = {}
    for team, players in (squads or {}).items():
        tbl = {}
        for p in players or []:
            name = p.get("name")
            if name:
                tbl[name] = {"pos": p.get("pos"), "apps": p.get("apps")}
        if tbl:
            out[team] = tbl
    return out


def derive_role_factors(results, squads):
    """Empiriska rollfaktorer ur facit: mål/spelare per positionsbucket,
    normaliserat mot F=1.0. Faller tillbaka på ROLE_FACTOR vid för lite data."""
    sq = squad_table(squads)
    if not sq:
        return dict(ROLE_FACTOR)
    by_team, _ = team_goal_table(results)
    goals_by_pos = {"F": 0.0, "M": 0.0, "D": 0.0, "G": 0.0}
    n_by_pos = {"F": 0, "M": 0, "D": 0, "G": 0}
    for team, tbl in sq.items():
        for name, meta in tbl.items():
            pos = meta.get("pos")
            if pos in n_by_pos:
                n_by_pos[pos] += 1
                goals_by_pos[pos] += by_team.get(team, {}).get(name, 0)
    total_goals = sum(goals_by_pos.values())
    if total_goals < 8 or n_by_pos["F"] == 0 or goals_by_pos["F"] <= 0:
        return dict(ROLE_FACTOR)               # för tunt → konservativa defaults
    rate = {p: (goals_by_pos[p] / n_by_pos[p]) if n_by_pos[p] else 0.0 for p in n_by_pos}
    f = rate["F"] or 1.0
    out = {p: max(0.0, min(1.0, rate[p] / f)) for p in rate}
    out["F"] = 1.0
    return out


def enriched_team_table(results, squads=None):
    """(by_team, totals, info): som team_goal_table men UNIONERAR in trupp-
    spelare (mållösa får mål=0) och bifogar info[lag][namn]={pos,apps}.
    squads tom/None → by_team/totals identiska med team_goal_table, info={}."""
    by_team, totals = team_goal_table(results)
    info = {}
    sq = squad_table(squads)
    for team, tbl in sq.items():
        bt = by_team.setdefault(team, {})
        totals.setdefault(team, 0)
        meta = info.setdefault(team, {})
        for name, m in tbl.items():
            bt.setdefault(name, 0)             # mållös trupp-spelare → 0 mål
            meta[name] = {"pos": m.get("pos"), "apps": m.get("apps")}
    return by_team, totals, info


def player_share(goals, team_total, k=K_SHRINK, n_outfield=N_OUTFIELD, role=ROLE_DEFAULT):
    """Empirisk-Bayes-andel av lagets mål: krymper mot baslinje·roll.
    role=1.0 (default) ger exakt det gamla beteendet (prior = 1/n_outfield)."""
    prior = (1.0 / n_outfield) * role
    denom = team_total + k
    return (goals + k * prior) / denom if denom > 0 else prior


def scorer_probs(lam_team, share, role=ROLE_DEFAULT):
    """(λ_spelare, P(anytime), P(2+)) ur Poisson. Rollen ligger i andelens prior,
    så role lämnas 1.0 här (param finns kvar för bakåtkompatibilitet)."""
    lam_p = max(0.0, lam_team * share * role)
    e = math.exp(-lam_p)
    return lam_p, max(0.0, 1.0 - e), max(0.0, 1.0 - e - lam_p * e)


def match_scorer_analysis(home, away, lam_home, lam_away, by_team, totals,
                          info=None, role_factors=None, top_n=TOP_N):
    """Topp-N anytime-kandidater för en match (sorterat på P(anytime)).

    info/role_factors (valfria) aktiverar truppberikning + rollviktad prior;
    utan dem är resultatet identiskt med scorers-only-läget."""
    info = info or {}
    rf = role_factors or {}
    rows = []
    for team, lam in ((home, lam_home), (away, lam_away)):
        tot = totals.get(team, 0)
        has_squad = bool(info.get(team))
        if tot < MIN_TEAM_GOALS and not has_squad:
            continue
        for name, g in by_team.get(team, {}).items():
            meta = info.get(team, {}).get(name, {})
            pos = meta.get("pos")
            role = rf.get(pos, ROLE_DEFAULT) if pos else ROLE_DEFAULT
            share = player_share(g, tot, role=role)
            lam_p, p1, p2 = scorer_probs(lam, share)
            row = {"player": name, "team": team, "groupGoals": g,
                   "lambda": round(lam_p, 3),
                   "pAnytime": round(p1, 3), "p2plus": round(p2, 3)}
            if info:                            # additiva berikningsfält
                row["position"] = pos
                row["apps"] = meta.get("apps")
                row["goalless"] = g == 0
            rows.append(row)
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
    # --- Bakåtkompatibilitet: utan squads identiskt med tidigare ---
    by_team, totals = team_goal_table(results)
    assert totals["Frankrike"] == 7 and by_team["Frankrike"]["Mbappé"] == 4
    bt2, tot2, info = enriched_team_table(results, None)
    assert bt2 == by_team and tot2 == totals and info == {}, "squads=None måste vara oförändrat"
    s_mbappe = player_share(4, 7); s_kolo = player_share(1, 7)
    assert s_mbappe > s_kolo > 0 and s_mbappe < 4 / 7
    rows = match_scorer_analysis("Frankrike", "Z", 1.8, 0.8, by_team, totals)
    assert rows and rows[0]["player"] == "Mbappé" and "position" not in rows[0]
    # --- Berikning: mållös anfallare syns, rollviktad ---
    squads = {"Frankrike": [
        {"name": "Mbappé", "pos": "F", "apps": 5, "goals": 4},
        {"name": "Saliba", "pos": "D", "apps": 5, "goals": 0},   # mållös försvarare
        {"name": "Olise", "pos": "F", "apps": 4, "goals": 0}]}   # mållös anfallare
    rf = derive_role_factors(results, squads)
    assert rf["F"] == 1.0 and rf["F"] >= rf["M"] >= rf["D"] >= rf["G"], rf
    bt3, tot3, info3 = enriched_team_table(results, squads)
    assert bt3["Frankrike"]["Olise"] == 0 and info3["Frankrike"]["Olise"]["pos"] == "F"
    rows3 = match_scorer_analysis("Frankrike", "Z", 1.8, 0.8, bt3, tot3, info3, rf)
    names = [r["player"] for r in rows3]
    assert "Olise" in names, "mållös anfallare ska få en rad"
    olise = next(r for r in rows3 if r["player"] == "Olise")
    saliba = next((r for r in rows3 if r["player"] == "Saliba"), None)
    assert olise["goalless"] is True and olise["position"] == "F"
    if saliba:
        assert olise["pAnytime"] > saliba["pAnytime"], "anfallare > försvarare vid 0 mål"
    print("  OK: Mbappé P(anytime)=%.3f; mållös anfallare Olise=%.3f%s"
          % (rows[0]["pAnytime"], olise["pAnytime"],
             "" if saliba is None else " > försvarare %.3f" % saliba["pAnytime"]))


if __name__ == "__main__":
    _selftest()
