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
  Fulltid · Antal mål (huvudlinje Ö/U) · Båda lagen gör mål ·
  Målgörare ("Gör mål") · Spelarspecial ("Gör Åtminstone 2 mål" +
  "Skott på mål från spelaren")
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


def fetch_match_markets(kambi_id):
    """Detaljmarknaderna för en match.

    Returnerar:
      {
        "fulltid":   {"1": o, "X": o, "2": o},
        "antal_mal": {"line": 2.5, "over": o, "under": o},
        "btts":      {"yes": o, "no": o},
        "malgorare": [{"player": n, "odds": o}],                  # Gör mål (Ja)
        "tvaplus":   [{"player": n, "odds": o}],                  # Gör Åtminstone 2 mål
        "skott":     [{"player": n, "line": 1.5, "odds": o}],     # Skott på mål, Över
      }
    """
    url = "%s/betoffer/event/%s.json?%s" % (KAMBI_BASE, kambi_id, KAMBI_QUERY)
    data = _get(url)
    res = {"fulltid": {}, "antal_mal": {}, "btts": {},
           "malgorare": [], "tvaplus": [], "skott": []}
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

        elif label == "Antal mål" and "MAIN_LINE" in tags:
            for o in open_outcomes:
                if o.get("label") == "Över":
                    res["antal_mal"]["over"] = _odds(o.get("odds"))
                    res["antal_mal"]["line"] = _line(o.get("line"))
                elif o.get("label") == "Under":
                    res["antal_mal"]["under"] = _odds(o.get("odds"))

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
        mk = fetch_match_markets(matches[0]["kambiId"])
        print("\nDetaljmarknader %s – %s: fulltid=%s, Ö/U=%s, btts=%s, "
              "målgörare=%d, 2+mål=%d, skott=%d" % (
                  matches[0]["home"], matches[0]["away"], mk["fulltid"],
                  mk["antal_mal"], mk["btts"], len(mk["malgorare"]),
                  len(mk["tvaplus"]), len(mk["skott"])))
