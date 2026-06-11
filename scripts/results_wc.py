#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Slutresultat för spelade VM-matcher — för appens automatiska rättning.

Primär källa:  football-data.org /v4/competitions/WC/matches (gratis-token i
               env FOOTBALLDATA_TOKEN — samma token som vm2026-facit-repot).
               Täcker ALLA matcher inkl. slutspel, matchas på lagnamn.
Reservkälla:   results.json från vm2026-facit-repot (ingen token). Den är
               nycklad på prognosens match-id:n, så slutspelsmatcher som
               divergerat från prognosen kan saknas där — gruppspelet täcks
               alltid.

Utdata: [{date, home, away, scoreHome, scoreAway}] med kanoniska kortnamn —
appen matchar sparade spel på (home, away).
"""
import json
import os
import sys
import urllib.request

from wc_data import TEAMS, short_of

FACIT_RESULTS_URL = "https://raw.githubusercontent.com/oscarsteinconsulting/vm2026-facit/main/results.json"
FOOTBALLDATA_URL = "https://api.football-data.org/v4/competitions/WC/matches?season=2026"

# Samma gruppspels-fixture-ordning som vm2026-facit (omgång 1-3 per grupp).
# Lagen sorteras fallande på MSS inom gruppen — index nedan pekar i den ordningen.
ROUNDROBIN = [((0, 3), (1, 2)), ((0, 2), (3, 1)), ((0, 1), (2, 3))]

# MSS-värden som facit använder för sorteringen (frysta, ur facit_update.py).
FACIT_MSS = {
    "Mexiko": 66, "Sydkorea": 60, "Tjeckien": 50, "Sydafrika": 44,
    "Schweiz": 67, "Kanada": 62, "Bosnien": 48, "Qatar": 49,
    "Brasilien": 83, "Marocko": 76, "Skottland": 52, "Haiti": 36,
    "Turkiet": 58, "USA": 64, "Paraguay": 51, "Australien": 55,
    "Tyskland": 80, "Ecuador": 60, "Elfenbenskusten": 51, "Curacao": 33,
    "Nederländerna": 78, "Japan": 69, "Sverige": 61, "Tunisien": 49,
    "Belgien": 77, "Egypten": 55, "Iran": 56, "Nya Zeeland": 37,
    "Spanien": 90, "Uruguay": 71, "Saudiarabien": 46, "Kap Verde": 38,
    "Frankrike": 91, "Senegal": 70, "Norge": 66, "Irak": 41,
    "Argentina": 89, "Österrike": 59, "Algeriet": 51, "Jordanien": 42,
    "Portugal": 82, "Colombia": 70, "DR Kongo": 44, "Uzbekistan": 45,
    "England": 84, "Kroatien": 72, "Ghana": 43, "Panama": 50,
}

DONE = {"FINISHED", "AWARDED"}


def _fetch(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=dict({"User-Agent": "stakbrons-vm-feed/1.0"},
                                                   **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _group_fixture_index():
    """{gruppmatch-id: (homeShort, awayShort)} — speglar facit_update.build_index."""
    groups = {}
    for (g, short, _elo, _flag) in TEAMS:
        groups.setdefault(g, []).append(short)
    idx = {}
    for letter in sorted(groups):
        g = sorted(groups[letter], key=lambda s: -FACIT_MSS[s])
        for omg, pairs in enumerate(ROUNDROBIN, start=1):
            for (a, b) in pairs:
                mid = "G%s%d%d%d" % (letter, omg, a, b)
                idx[mid] = (g[a], g[b])
    return idx


def from_football_data(token):
    out = []
    data = _fetch(FOOTBALLDATA_URL, headers={"X-Auth-Token": token, "Accept": "application/json"})
    for m in data.get("matches") or []:
        if m.get("status") not in DONE:
            continue
        hn = (m.get("homeTeam") or {}).get("name")
        an = (m.get("awayTeam") or {}).get("name")
        ft = (m.get("score") or {}).get("fullTime") or {}
        h, a = ft.get("home"), ft.get("away")
        home, away = short_of(hn or ""), short_of(an or "")
        if home and away and isinstance(h, int) and isinstance(a, int):
            out.append({"date": (m.get("utcDate") or "")[:10],
                        "home": home, "away": away,
                        "scoreHome": h, "scoreAway": a})
    return out


def from_facit():
    out = []
    results = _fetch(FACIT_RESULTS_URL)
    if not isinstance(results, dict):
        return out
    idx = _group_fixture_index()
    for mid, score in results.items():
        pair = idx.get(mid)
        if not pair or not isinstance(score, (list, tuple)) or len(score) != 2:
            continue  # slutspels-id:n (M73+) kan inte mappas säkert utan token-vägen
        out.append({"date": None, "home": pair[0], "away": pair[1],
                    "scoreHome": int(score[0]), "scoreAway": int(score[1])})
    return out


def fetch_results():
    token = (os.environ.get("FOOTBALLDATA_TOKEN") or "").strip()
    if token:
        try:
            res = from_football_data(token)
            print("  resultat: %d färdigspelade via football-data.org" % len(res))
            return res
        except Exception as e:
            print("  ! football-data.org failade: %s — provar facit-reserven" % e, file=sys.stderr)
    try:
        res = from_facit()
        print("  resultat: %d färdigspelade via vm2026-facit (reserv)" % len(res))
        return res
    except Exception as e:
        print("  ! facit-reserven failade också: %s" % e, file=sys.stderr)
        return []


if __name__ == "__main__":
    for r in fetch_results():
        print(r)
