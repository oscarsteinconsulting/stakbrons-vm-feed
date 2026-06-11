#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hämtar Svenska Spels VM-odds från Kambis publika CDN — samma mönster som
stakbrons-golf-feed/scripts/kambi_odds.py (hittat via DevTools på
spela.svenskaspel.se; odds lagras som heltal ÷ 1000, linjer likaså).

  1. listView/football/world_cup_2026/all/all/matches.json
       → alla kommande VM-matcher med huvudodds (Fulltid + Antal mål)
  2. betoffer/event/{id}.json
       → alla ~700 marknader för en match; hämtas bara för dagens matcher

Marknader vi plockar (kategorierna från Svenska Spels VM-meny):
  Fulltid · Dubbelchans · Handikapp (Asian handicap, halvlinjer) ·
  Antal mål (huvudlinje Ö/U + lagmål) · Båda lagen gör mål ·
  Korrekt resultat · Halvtid (1X2 + Ö/U första halvlek) · Halvtid/Fulltid ·
  Målgörare ("Gör mål") · Spelarspecial ("Gör Åtminstone 2 mål" +
  "Skott på mål från spelaren") · Hörnor · Kort
"""
import json
import sys
import urllib.request

from wc_data import short_of

KAMBI_BASE = "https://eu.offering-api.kambicdn.com/offering/v2018/svenskaspel"
KAMBI_QUERY = "channel_id=1&client_id=200&lang=sv_SE&market=SE&useCombined=true&useCombinedLive=true"
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605.1.15"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def _odds(raw):
    if raw is None:
        return None
    try:
        v = float(raw) / 1000.0
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def _line(raw):
    if raw is None:
        return None
    try:
        return float(raw) / 1000.0
    except (TypeError, ValueError):
        return None


def fetch_match_list():
    """Alla listade VM-matcher med huvudodds.

    [{kambiId, home, away, homeRaw, awayRaw, kickoff, odds1, oddsX, odds2,
      ouLine, oddsOver, oddsUnder}]  — home/away är kanoniska kortnamn.
    """
    url = "%s/listView/football/world_cup_2026/all/all/matches.json?%s" % (KAMBI_BASE, KAMBI_QUERY)
    data = _get(url)
    out = []
    for wrapper in data.get("events", []):
        ev = wrapper.get("event") or {}
        if ev.get("state") == "STARTED":
            continue
        name = ev.get("name", "")
        if " - " not in name:
            continue
        home_raw, away_raw = [s.strip() for s in name.split(" - ", 1)]
        home, away = short_of(home_raw), short_of(away_raw)
        if not home or not away:
            print("  ! okänt lag i Kambi-namn: %r" % name, file=sys.stderr)
            continue
        row = {
            "kambiId": str(ev["id"]),
            "home": home, "away": away,
            "homeRaw": home_raw, "awayRaw": away_raw,
            "kickoff": ev.get("start"),
            "odds1": None, "oddsX": None, "odds2": None,
            "ouLine": None, "oddsOver": None, "oddsUnder": None,
        }
        for bo in wrapper.get("betOffers") or []:
            label = (bo.get("criterion") or {}).get("label")
            if label == "Fulltid":
                for o in bo.get("outcomes", []):
                    if o.get("label") == "1":
                        row["odds1"] = _odds(o.get("odds"))
                    elif o.get("label") == "X":
                        row["oddsX"] = _odds(o.get("odds"))
                    elif o.get("label") == "2":
                        row["odds2"] = _odds(o.get("odds"))
            elif label == "Antal mål":
                for o in bo.get("outcomes", []):
                    if o.get("label") == "Över":
                        row["oddsOver"] = _odds(o.get("odds"))
                        row["ouLine"] = _line(o.get("line"))
                    elif o.get("label") == "Under":
                        row["oddsUnder"] = _odds(o.get("odds"))
        out.append(row)
    return out


def _over_under(open_outcomes):
    """(line, over, under) ur en Ö/U-marknads öppna outcomes."""
    line = over = under = None
    for o in open_outcomes:
        if o.get("label") == "Över":
            over = _odds(o.get("odds"))
            line = _line(o.get("line"))
        elif o.get("label") == "Under":
            under = _odds(o.get("odds"))
    return line, over, under


def _most_balanced(cands):
    """Välj linjen vars Över/Under-odds ligger närmast varandra (jämnast
    marknad ≈ marknadens egen huvudlinje). cands = [(line, over, under)]."""
    best = None
    for line, over, under in cands:
        if line is None or not over or not under:
            continue
        gap = abs(over - under)
        if best is None or gap < best[0]:
            best = (gap, line, over, under)
    if best is None:
        return {}
    return {"line": best[1], "over": best[2], "under": best[3]}


def _team_side(name, home, away):
    """Lagnamn ur criterion-labelns suffix → "home"/"away" via short_of.
    Halvleksvarianter ("... - Första halvlek") faller bort på " - "."""
    if not home or not away or " - " in name:
        return None
    short = short_of(name.strip())
    if short == home:
        return "home"
    if short == away:
        return "away"
    return None


def fetch_match_markets(kambi_id, home=None, away=None):
    """Detaljmarknaderna för en match. home/away (kanoniska kortnamn) krävs
    för lag-marknaderna (handikapp, lagmål, lag-hörnor, lag-kort) — utan dem
    hoppas de över (bakåtkompatibelt).

    Returnerar:
      {
        "fulltid":          {"1": o, "X": o, "2": o},
        "dubbelchans":      {"1X": o, "12": o, "X2": o},
        "handikapp":        {"line": -1.5, "home": o, "away": o},   # halvlinje, mest balanserad
        "antal_mal":        {"line": 2.5, "over": o, "under": o},
        "lagmal":           {"home": {"line", "over", "under"}, "away": {...}},
        "btts":             {"yes": o, "no": o},
        "korrekt_resultat": {"1-0": o, "2-1": o, ...},
        "halvtid_1x2":      {"1": o, "X": o, "2": o},               # första halvlekens resultat
        "antal_mal_1h":     {"line": 0.5, "over": o, "under": o},
        "halvtid_fulltid":  {"1/1": o, ..., "2/2": o},
        "malgorare":        [{"player": n, "odds": o}],             # Gör mål (Ja)
        "tvaplus":          [{"player": n, "odds": o}],             # Gör Åtminstone 2 mål
        "skott":            [{"player": n, "line": 1.5, "odds": o}],# Skott på mål, Över
        "hornor":           {"line": 9.5, "over": o, "under": o},
        "hornor_lag":       {"home": {...}, "away": {...}},
        "kort":             {"line": 3.5, "over": o, "under": o},
        "kort_lag":         {"home": {...}, "away": {...}},
      }
    """
    url = "%s/betoffer/event/%s.json?%s" % (KAMBI_BASE, kambi_id, KAMBI_QUERY)
    data = _get(url)
    res = {"fulltid": {}, "dubbelchans": {}, "handikapp": {}, "antal_mal": {},
           "lagmal": {}, "btts": {}, "korrekt_resultat": {}, "halvtid_1x2": {},
           "antal_mal_1h": {}, "halvtid_fulltid": {},
           "malgorare": [], "tvaplus": [], "skott": [],
           "hornor": {}, "hornor_lag": {}, "kort": {}, "kort_lag": {}}
    ah_cands = []      # Asian handicap-halvlinjer: (line, hemmaodds, bortaodds)
    ou1h_cands = []    # Antal mål 1:a halvlek utan MAIN_LINE-tag
    hornor_cands = []  # Antal hörnor (alla linjer)
    for bo in data.get("betOffers", []):
        if bo.get("closed") is True:
            continue
        label = (bo.get("criterion") or {}).get("label") or ""
        tags = bo.get("tags") or []
        outcomes = bo.get("outcomes", [])
        open_outcomes = [o for o in outcomes if o.get("status", "OPEN") == "OPEN"]

        if label == "Fulltid" and "MAIN" in tags:
            for o in open_outcomes:
                if o.get("label") in ("1", "X", "2"):
                    res["fulltid"][o["label"]] = _odds(o.get("odds"))

        elif label == "Dubbelchans":
            for o in open_outcomes:
                if o.get("label") in ("1X", "12", "X2"):
                    res["dubbelchans"][o["label"]] = _odds(o.get("odds"))

        elif label in ("Asian handicap", "Asian handicap "):
            # OBS: Kambi-labeln har trailing space. Outcomes är lagnamn —
            # mappas via short_of. Bara halvlinjer (.5) behålls: de kan
            # aldrig sluta push och rättas entydigt mot slutresultatet.
            row = {}
            for o in open_outcomes:
                side = _team_side(o.get("participant") or o.get("label") or "",
                                  home, away)
                if side == "home":
                    row["home"] = _odds(o.get("odds"))
                    row["line"] = _line(o.get("line"))   # linjen ur HEMMA-lagets outcome
                elif side == "away":
                    row["away"] = _odds(o.get("odds"))
            line = row.get("line")
            if (line is not None and row.get("home") and row.get("away")
                    and abs(line) % 1.0 == 0.5):
                ah_cands.append((line, row["home"], row["away"]))

        elif label == "Antal mål" and "MAIN_LINE" in tags:
            for o in open_outcomes:
                if o.get("label") == "Över":
                    res["antal_mal"]["over"] = _odds(o.get("odds"))
                    res["antal_mal"]["line"] = _line(o.get("line"))
                elif o.get("label") == "Under":
                    res["antal_mal"]["under"] = _odds(o.get("odds"))

        elif label == "Antal mål - Första halvlek":
            line, over, under = _over_under(open_outcomes)
            if line is not None and over and under:
                if "MAIN_LINE" in tags:
                    res["antal_mal_1h"] = {"line": line, "over": over, "under": under}
                else:
                    ou1h_cands.append((line, over, under))

        elif label.startswith("Antal mål för ") and "MAIN_LINE" in tags:
            side = _team_side(label[len("Antal mål för "):], home, away)
            if side:
                line, over, under = _over_under(open_outcomes)
                if line is not None and over and under:
                    res["lagmal"][side] = {"line": line, "over": over, "under": under}

        elif label == "Korrekt resultat":
            for o in open_outcomes:
                lab = o.get("label") or ""
                odds = _odds(o.get("odds"))
                if odds and "-" in lab:
                    res["korrekt_resultat"][lab] = odds

        elif label == "Halvtid":
            # Betoffer-typ "Match": 1/X/2 för FÖRSTA halvlekens resultat
            for o in open_outcomes:
                if o.get("label") in ("1", "X", "2"):
                    res["halvtid_1x2"][o["label"]] = _odds(o.get("odds"))

        elif label == "Halvtid/Fulltid":
            for o in open_outcomes:
                lab = o.get("label") or ""
                odds = _odds(o.get("odds"))
                if odds and "/" in lab:
                    res["halvtid_fulltid"][lab] = odds

        elif label == "Antal hörnor":
            line, over, under = _over_under(open_outcomes)
            hornor_cands.append((line, over, under))

        elif label.startswith("Antal hörnor för ") and "MAIN_LINE" in tags:
            side = _team_side(label[len("Antal hörnor för "):], home, away)
            if side:
                line, over, under = _over_under(open_outcomes)
                if line is not None and over and under:
                    res["hornor_lag"][side] = {"line": line, "over": over, "under": under}

        elif label == "Antal kort" and "MAIN_LINE" in tags:
            line, over, under = _over_under(open_outcomes)
            if line is not None and over and under:
                res["kort"] = {"line": line, "over": over, "under": under}

        elif label.startswith("Antal kort - ") and "MAIN_LINE" in tags:
            side = _team_side(label[len("Antal kort - "):], home, away)
            if side:
                line, over, under = _over_under(open_outcomes)
                if line is not None and over and under:
                    res["kort_lag"][side] = {"line": line, "over": over, "under": under}

        elif label == "Båda lagen gör mål":
            for o in open_outcomes:
                if o.get("label") == "Ja":
                    res["btts"]["yes"] = _odds(o.get("odds"))
                elif o.get("label") == "Nej":
                    res["btts"]["no"] = _odds(o.get("odds"))

        elif label == "Gör mål":
            for o in open_outcomes:
                player = o.get("participant")
                odds = _odds(o.get("odds"))
                if player and odds:
                    res["malgorare"].append({"player": player, "odds": odds})

        elif label == "Gör Åtminstone 2 mål":
            for o in open_outcomes:
                player = o.get("participant")
                odds = _odds(o.get("odds"))
                if player and odds:
                    res["tvaplus"].append({"player": player, "odds": odds})

        elif label.startswith("Skott på mål från spelaren"):
            for o in open_outcomes:
                player = o.get("participant")
                odds = _odds(o.get("odds"))
                line = _line(o.get("line"))
                if player and odds and o.get("label") == "Över" and line is not None:
                    res["skott"].append({"player": player, "line": line, "odds": odds})

    # Handikapp: bland halvlinjerna väljs den med mest balanserade odds —
    # den ligger närmast styrkeskillnaden och har minst marginalbrus.
    if ah_cands:
        best = min(ah_cands, key=lambda c: abs(c[1] - c[2]))
        res["handikapp"] = {"line": best[0], "home": best[1], "away": best[2]}
    # Antal mål 1:a halvlek: MAIN_LINE-taggen vinner, annars jämnaste linjen.
    if not res["antal_mal_1h"]:
        res["antal_mal_1h"] = _most_balanced(ou1h_cands)
    # Hörnor: ingen MAIN_LINE-preferens — jämnaste linjen är huvudlinjen.
    res["hornor"] = _most_balanced(hornor_cands)
    return res


if __name__ == "__main__":
    matches = fetch_match_list()
    print("Hämtade %d VM-matcher från Kambi:" % len(matches))
    for m in matches[:8]:
        print("  %s  %s – %s  1X2: %s/%s/%s  Ö/U %.1f: %s/%s" % (
            (m["kickoff"] or "")[:16], m["home"], m["away"],
            m["odds1"], m["oddsX"], m["odds2"],
            m["ouLine"] or 0, m["oddsOver"], m["oddsUnder"]))
    if matches:
        m0 = matches[0]
        mk = fetch_match_markets(m0["kambiId"], m0["home"], m0["away"])
        print("\nDetaljmarknader %s – %s: fulltid=%s, Ö/U=%s, btts=%s, "
              "målgörare=%d, 2+mål=%d, skott=%d" % (
                  m0["home"], m0["away"], mk["fulltid"],
                  mk["antal_mal"], mk["btts"], len(mk["malgorare"]),
                  len(mk["tvaplus"]), len(mk["skott"])))
        print("  dubbelchans=%s handikapp=%s halvtid=%s Ö/U-1H=%s" % (
            mk["dubbelchans"], mk["handikapp"], mk["halvtid_1x2"], mk["antal_mal_1h"]))
        print("  korrekt resultat=%d utfall, HT/FT=%d, lagmål=%s" % (
            len(mk["korrekt_resultat"]), len(mk["halvtid_fulltid"]), mk["lagmal"]))
        print("  hörnor=%s lag=%s kort=%s lag=%s" % (
            mk["hornor"], mk["hornor_lag"], mk["kort"], mk["kort_lag"]))
