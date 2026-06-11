#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VM-tipset-kupongen från Svenska Spel → feed-sektionen "vmtipset".

Hämtar öppna omgångar från Svenska Spels publika draw-API. OBS: VM-tipset
SAMSAS med Europatipset på samma rutt (productId 2) — därför filtreras
draws-listan på productName == "VM-tipset" och drawState == "Open".
Ingen öppen omgång → sektionen blir None (appen avkodar fältet som optional).

Per match levereras kupongens odds och svenska folkets procent rakt av,
plus modellens 1X2 (Oscars funderingar, wc_model.MatchModel) krympt mot
kupongoddsens avvigade priser — samma ödmjukhetsprincip som övriga spel.

Lagnamn tas ur match.participants (type home/away, fältet "name") —
eventDescription är TRUNKERAD ("Bosnien/H", "Australie", "Nederländ", ...)
och duger inte för mappning. Namnen normaliseras till kanoniska kortnamn
via wc_data.short_of; kan ett lag inte mappas tas matchen med ändå med
de avvigade kupongoddsen som sannolikheter (ingen modell) + varning.

Körs utan pip-paket (bara standardbiblioteket), Python 3.9+.
Självtest utan nät: python3 scripts/vmtipset.py --selftest
"""
import json
import sys
import time
import urllib.request

from wc_data import short_of, FLAG_OF
from wc_model import MatchModel, devig, shrink

DRAWS_URL = "https://api.spela.svenskaspel.se/draw/1/europatipset/draws"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605.1.15"

NOTE = ("Modellens 1X2-sannolikheter (Oscars funderingar, krympta mot oddsen) "
        "styr systemförslaget — appen optimerar garderingarna inom din maxinsats.")


# ---------------------------------------------------------------------------
# Parsning av Svenska Spels talformat
# ---------------------------------------------------------------------------

def _sv_float(s):
    """Svensk decimalkomma-sträng ("1,42" / "1,00") → float, annars None."""
    if s is None:
        return None
    try:
        return float(str(s).strip().replace(",", "."))
    except ValueError:
        return None


def _sv_int(s):
    """Procentsträng ("76") → int, annars None."""
    if s is None:
        return None
    try:
        return int(str(s).strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Hämtning + draw-urval
# ---------------------------------------------------------------------------

def _fetch_draws(timeout=30):
    url = "%s?_=%d" % (DRAWS_URL, int(time.time() * 1000))
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _pick_open_draw(payload):
    """Första öppna VM-tipset-omgången ur draws-svaret, eller None.
    Rutten delas med Europatipset — productName måste matcha exakt."""
    for dr in (payload or {}).get("draws") or []:
        if dr.get("productName") == "VM-tipset" and dr.get("drawState") == "Open":
            return dr
    return None


# ---------------------------------------------------------------------------
# Sektionsbygget
# ---------------------------------------------------------------------------

def _participant_name(ev, side):
    """Lagnamn ur match.participants — INTE eventDescription (trunkerad)."""
    for p in ((ev.get("match") or {}).get("participants") or []):
        if p.get("type") == side:
            return p.get("name")
    return None


def _build_match(ev, ratings):
    """En kupongmatch → platt dict enligt feed-kontraktet."""
    raw_home = _participant_name(ev, "home")
    raw_away = _participant_name(ev, "away")

    odds = ev.get("odds") or {}
    o1 = _sv_float(odds.get("one"))
    ox = _sv_float(odds.get("x"))
    o2 = _sv_float(odds.get("two"))
    market = devig([o1, ox, o2])  # None om något odds saknas/är ogiltigt

    folket = ev.get("svenskaFolket") or {}

    home = short_of(raw_home) if raw_home else None
    away = short_of(raw_away) if raw_away else None

    if home and away and home in ratings and away in ratings:
        # Modellens 1X2 krympt mot kupongens avvigade priser per utfall,
        # sedan normaliserad så att trippeln summerar till exakt 1.0.
        ph, pd, pa = MatchModel(home, away, ratings).p_1x2()
        if market:
            ph = shrink(ph, market[0])
            pd = shrink(pd, market[1])
            pa = shrink(pa, market[2])
        tot = ph + pd + pa
        ph, pd, pa = ph / tot, pd / tot, pa / tot
    else:
        # Omappat lag: ta med matchen ändå — avvigade kupongodds rakt av.
        print("  ! vmtipset: kunde inte mappa %r/%r — använder avvigade "
              "kupongodds utan modell" % (raw_home, raw_away), file=sys.stderr)
        if market:
            ph, pd, pa = market
        else:
            ph = pd = pa = 1.0 / 3.0  # inte ens odds fanns — neutral gissning
        home = home or raw_home or "?"
        away = away or raw_away or "?"

    return {
        "n": ev.get("eventNumber"),
        "home": home, "away": away,
        "homeFlag": FLAG_OF.get(home, ""), "awayFlag": FLAG_OF.get(away, ""),
        "pHome": round(ph, 4), "pDraw": round(pd, 4), "pAway": round(pa, 4),
        "folketOne": _sv_int(folket.get("one")),
        "folketX": _sv_int(folket.get("x")),
        "folketTwo": _sv_int(folket.get("two")),
        "oddsOne": o1, "oddsX": ox, "oddsTwo": o2,
    }


def _build_section(draw, ratings):
    events = sorted(draw.get("drawEvents") or [], key=lambda e: e.get("eventNumber") or 0)
    return {
        "drawNumber": draw.get("drawNumber"),
        "productName": draw.get("productName"),
        "closeTime": draw.get("regCloseTime"),  # ISO med offset, svensk tid
        "rowPriceKr": _sv_float(draw.get("rowPrice")),
        "note": NOTE,
        "matches": [_build_match(ev, ratings) for ev in events],
    }


def build_vmtipset_section(ratings, date_str):
    """Feed-sektionen "vmtipset", eller None när ingen omgång är öppen.

    `date_str` används inte i bygget (kupongen styrs av regCloseTime) men
    behålls i signaturen för symmetri med tournament-sektionen."""
    payload = _fetch_draws()
    draw = _pick_open_draw(payload)
    if draw is None:
        return None
    return _build_section(draw, ratings)


# ---------------------------------------------------------------------------
# Självtest — kör mappning/parsning mot ett inbäddat draw-exempel utan nät.
# Klippt ur det riktiga svaret 2026-06-11 (nedbantat till 3 events; notera
# de trunkerade eventDescription-fälten som INTE får användas för mappning).
# ---------------------------------------------------------------------------

_SAMPLE = {
    "draws": [
        {  # fel produkt på samma rutt — ska filtreras bort
            "productName": "Europatipset", "drawState": "Open",
            "drawNumber": 9999, "rowPrice": "1,00", "drawEvents": [],
        },
        {
            "productName": "VM-tipset", "drawState": "Open",
            "drawNumber": 2582, "rowPrice": "1,00",
            "regCloseTime": "2026-06-11T20:59:00+02:00",
            "drawEvents": [
                {
                    "eventNumber": 1,
                    "eventDescription": "Mexiko - Sydafrika",
                    "match": {"participants": [
                        {"type": "home", "name": "Mexiko"},
                        {"type": "away", "name": "Sydafrika"},
                    ]},
                    "odds": {"one": "1,42", "x": "4,70", "two": "9,00"},
                    "svenskaFolket": {"one": "76", "x": "18", "two": "6"},
                },
                {
                    "eventNumber": 3,
                    # trunkerad beskrivning — participants.name gäller
                    "eventDescription": "Kanada - Bosnien/H",
                    "match": {"participants": [
                        {"type": "home", "name": "Kanada"},
                        {"type": "away", "name": "Bosnien & Hercegovina"},
                    ]},
                    "odds": {"one": "1,85", "x": "3,50", "two": "5,00"},
                    "svenskaFolket": {"one": "49", "x": "31", "two": "20"},
                },
                {
                    "eventNumber": 13,
                    # påhittat omappbart lag — fallback till avvigade odds
                    "eventDescription": "Argentina - Atlantis",
                    "match": {"participants": [
                        {"type": "home", "name": "Argentina"},
                        {"type": "away", "name": "Atlantis"},
                    ]},
                    "odds": {"one": "1,40", "x": "4,90", "two": "10,00"},
                    "svenskaFolket": {"one": "82", "x": "14", "two": "4"},
                },
            ],
        },
    ],
}

_CONTRACT_MATCH_KEYS = {
    "n", "home", "away", "homeFlag", "awayFlag",
    "pHome", "pDraw", "pAway",
    "folketOne", "folketX", "folketTwo",
    "oddsOne", "oddsX", "oddsTwo",
}


def _selftest():
    ratings = {"Mexiko": 1850.0, "Sydafrika": 1520.0,
               "Kanada": 1780.0, "Bosnien": 1660.0, "Argentina": 2100.0}

    # Decimalkomma-parsning
    assert _sv_float("1,42") == 1.42
    assert _sv_float("1,00") == 1.0
    assert _sv_int("76") == 76
    assert _sv_float(None) is None and _sv_int("") is None

    # Draw-filtret: rätt produkt + öppen omgång, annars None
    draw = _pick_open_draw(_SAMPLE)
    assert draw is not None and draw["drawNumber"] == 2582
    assert _pick_open_draw({"draws": [{"productName": "Europatipset",
                                       "drawState": "Open"}]}) is None
    assert _pick_open_draw({"draws": [{"productName": "VM-tipset",
                                       "drawState": "Closed"}]}) is None

    sec = _build_section(draw, ratings)
    assert sec["drawNumber"] == 2582
    assert sec["productName"] == "VM-tipset"
    assert sec["closeTime"] == "2026-06-11T20:59:00+02:00"
    assert sec["rowPriceKr"] == 1.0
    assert isinstance(sec["note"], str) and sec["note"]
    assert len(sec["matches"]) == 3

    for mt in sec["matches"]:
        assert set(mt.keys()) == _CONTRACT_MATCH_KEYS, sorted(mt.keys())
        assert abs(mt["pHome"] + mt["pDraw"] + mt["pAway"] - 1.0) < 0.005, mt
        # platta heltal/floats — inga nästlade dicts
        assert isinstance(mt["folketOne"], int)
        assert isinstance(mt["oddsOne"], float)

    m1, m3, m13 = sec["matches"]
    assert m1["n"] == 1 and m1["home"] == "Mexiko" and m1["away"] == "Sydafrika"
    assert m1["homeFlag"] == "🇲🇽" and m1["awayFlag"] == "🇿🇦"
    assert m1["oddsOne"] == 1.42 and m1["oddsX"] == 4.70 and m1["oddsTwo"] == 9.00
    assert m1["folketOne"] == 76 and m1["folketX"] == 18 and m1["folketTwo"] == 6
    assert m1["pHome"] > m1["pDraw"] and m1["pHome"] > m1["pAway"]

    # Trunkerad eventDescription får inte styra — participants.name mappas
    assert m3["away"] == "Bosnien" and m3["awayFlag"] == "🇧🇦"

    # Omappat lag: avvigade kupongodds rakt av
    mk = devig([1.40, 4.90, 10.00])
    assert m13["away"] == "Atlantis" and m13["awayFlag"] == ""
    assert abs(m13["pHome"] - round(mk[0], 4)) < 1e-9

    print("vmtipset selftest: OK (%d matcher, kontraktets fältnamn, "
          "decimalkomma, p-summa ≈ 1)" % len(sec["matches"]))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        # Manuell skarp körning: hämta kupongen med neutrala ratings går inte
        # (modellen kräver riktiga lagstyrkor) — använd build_ratings.
        from wc_model import build_ratings
        ratings, _mss, _src = build_ratings()
        print(json.dumps(build_vmtipset_section(ratings, None),
                         ensure_ascii=False, indent=1))
