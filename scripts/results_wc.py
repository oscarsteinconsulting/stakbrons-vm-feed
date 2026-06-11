#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Slutresultat för spelade VM-matcher — för appens automatiska rättning.

Primär källa:  football-data.org /v4/competitions/WC/matches (gratis-token i
               env FOOTBALLDATA_TOKEN — samma token som vm2026-facit-repot).
               Täcker ALLA matcher inkl. slutspel, matchas på lagnamn.
               Detaljanropet /v4/matches/{id} berikar med målgörare (cachas
               persistent i data/results_cache.json — committas av workflowen).
Reservkälla:   results.json från vm2026-facit-repot (ingen token). Den är
               nycklad på prognosens match-id:n, så slutspelsmatcher som
               divergerat från prognosen kan saknas där — gruppspelet täcks
               alltid. Reserven ger BARA slutresultat: alla nya fält blir null.

Utdata-resultatpost (nya fält är optionella/null så gamla appar inte bryts):
  {date, home, away,
   scoreHome, scoreAway,     # 90-MINUTERSRESULTAT (regularTime vid förlängning)
   htHome, htAway,           # halvtidsresultat (null om okänt)
   duration,                 # "REGULAR"|"EXTRA_TIME"|"PENALTY_SHOOTOUT"|null
   winner,                   # "home"|"away"|"draw"|null — avancemang INKL. straffar
   scorers}                  # [{name, team, goals}] — EJ straffläggningsmål, null om okänt

fetch_results() returnerar (results, progress) där progress beskriver
turneringsmarknaderna (topp16/topp8/topp4/topp2/vinnare) — se build_progress().

Självtest utan nät: python3 scripts/results_wc.py --selftest
"""
import json
import os
import sys
import time
import urllib.request

from wc_data import TEAMS, short_of, stage_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "results_cache.json")

FACIT_RESULTS_URL = "https://raw.githubusercontent.com/oscarsteinconsulting/vm2026-facit/main/results.json"
FOOTBALLDATA_URL = "https://api.football-data.org/v4/competitions/WC/matches?season=2026"
MATCH_DETAIL_URL = "https://api.football-data.org/v4/matches/%s"

# Gratis-token hos football-data.org tillåter 10 anrop/minut — sov mellan
# detaljanropen så en spelomgångs alla nya matcher hinner hämtas utan 429.
DETAIL_SLEEP_S = 6.5

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

DURATIONS = {"REGULAR", "EXTRA_TIME", "PENALTY_SHOOTOUT"}
WINNER_OF = {"HOME_TEAM": "home", "AWAY_TEAM": "away", "DRAW": "draw"}

# Slutspelsfas (wc_data.stage_for) → turneringsmarknad + antal matcher i steget.
# Bronsmatchen ingår medvetet inte — den påverkar ingen topp-N-marknad.
KNOCKOUT_MARKETS = [
    ("Sextondelsfinal", "topp16", 16),
    ("Åttondelsfinal",  "topp8",   8),
    ("Kvartsfinal",     "topp4",   4),
    ("Semifinal",       "topp2",   2),
    ("Final",           "vinnare", 1),
]


def _fetch(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=dict({"User-Agent": "stakbrons-vm-feed/1.0"},
                                                   **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Persistent detaljcache: {matchId(str): {scorers, ht, regular, duration, winner}}
# Redan hämtade matcher hämtas ALDRIG om — filen committas av workflowens
# git-steg (den ligger i data/ som redan ingår i auto-committen).
# ---------------------------------------------------------------------------

def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)


def _int_pair(d):
    """{home, away} → [h, a] om båda är heltal, annars None."""
    h, a = (d or {}).get("home"), (d or {}).get("away")
    return [h, a] if isinstance(h, int) and isinstance(a, int) else None


def _aggregate_scorers(goals):
    """goals[]-arrayen från /v4/matches/{id} → [{name, team, goals}].

    - Straffläggningsmål ligger inte i goals[] (de ligger i penalties[]),
      vilket är precis vad vi vill: anytime-målgörare hos spelbolagen
      exkluderar straffläggningen.
    - Egna mål (type == "OWN") exkluderas — självmål räknas inte som
      målgörare hos spelbolagen.
    - Vanliga straffar under matchen (type == "PENALTY") räknas förstås.
    """
    counts, order = {}, []
    for g in goals or []:
        if (g.get("type") or "").upper() == "OWN":
            continue
        name = ((g.get("scorer") or {}).get("name") or "").strip()
        if not name:
            continue
        raw_team = ((g.get("team") or {}).get("name")) or ""
        team = short_of(raw_team) or raw_team or None
        key = (name, team)
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
    return [{"name": n, "team": t, "goals": counts[(n, t)]} for (n, t) in order]


def _entry_from_detail(d, mid="?"):
    """Detaljsvaret från /v4/matches/{id} → cache-post, eller None om svaret
    är ofullständigt (None cachas aldrig — matchen försöks om nästa körning)."""
    goals = d.get("goals")
    if goals is None:
        # goals[] saknas i svaret — cacha inte, så vi försöker igen nästa körning
        print("  ! matchdetalj %s saknar goals[] — scorers blir null" % mid, file=sys.stderr)
        return None
    score = d.get("score") or {}
    entry = {
        "scorers": _aggregate_scorers(goals),
        "ht": _int_pair(score.get("halfTime")),
        "regular": _int_pair(score.get("regularTime")),
        "duration": score.get("duration"),
        "winner": score.get("winner"),
    }
    if (entry["duration"] or "REGULAR") != "REGULAR" and entry["regular"] is None:
        # Förlängnings-/straffmatch utan regularTime: utan den kan 90-minuters-
        # resultatet aldrig fastställas via cachen. Cacha INTE — annars skulle
        # matchen (om även listsvaret saknar regularTime) hoppas över för
        # alltid i stället för att försökas om nästa körning.
        print("  ! matchdetalj %s saknar regularTime (duration=%s) — cachas ej"
              % (mid, entry["duration"]), file=sys.stderr)
        return None
    return entry


def _fetch_detail_entry(token, mid):
    """Hämtar /v4/matches/{id} och bygger cache-posten, eller None vid fel.

    None cachas inte — matchen försöks om nästa körning, och resultatposten
    får scorers=null så appen faller tillbaka på manuell rättning."""
    try:
        time.sleep(DETAIL_SLEEP_S)  # rate limit: 10 anrop/min på gratis-token
        d = _fetch(MATCH_DETAIL_URL % mid,
                   headers={"X-Auth-Token": token, "Accept": "application/json"})
    except Exception as e:
        print("  ! matchdetalj %s failade: %s" % (mid, e), file=sys.stderr)
        return None
    return _entry_from_detail(d, mid)


def _score90(score, entry):
    """90-minutersresultatet ur ett football-data score-objekt.

    VIKTIGT (buggfix): score.fullTime hos football-data INKLUDERAR
    förlängningen (men inte straffläggningen) i slutspelsmatcher. Spel på
    "Fulltid" (1X2/Över-Under/BTTS/Korrekt resultat/Handikapp) rättas enligt
    spelbolagskonvention på 90 MINUTER — därför används score.regularTime så
    fort duration != "REGULAR". Avancemanget (inkl. straffläggning) täcks i
    stället av winner-fältet. `entry` (detaljcachen) är reserv om listsvaret
    saknar regularTime."""
    dur = score.get("duration")
    if dur and dur != "REGULAR":
        pair = _int_pair(score.get("regularTime"))
        if pair is None and entry:
            pair = entry.get("regular")
        return tuple(pair) if pair else (None, None)
    ft = score.get("fullTime") or {}
    return ft.get("home"), ft.get("away")


def _build_row(m, home, away, entry):
    """En match ur listsvaret (+ ev. detaljcache-post) → resultatpost.
    None om 90-minutersresultatet inte kan fastställas (försöks om nästa
    körning när detaljanropet lyckats)."""
    score = m.get("score") or {}
    h, a = _score90(score, entry)
    if not (isinstance(h, int) and isinstance(a, int)):
        print("  ! %s–%s: 90-minutersresultat saknas (duration=%s) — hoppar"
              % (home, away, score.get("duration")), file=sys.stderr)
        return None
    ht = _int_pair(score.get("halfTime"))
    if ht is None and entry:
        ht = entry.get("ht")
    dur = score.get("duration")
    return {
        "date": (m.get("utcDate") or "")[:10] or None,
        "home": home, "away": away,
        "scoreHome": h, "scoreAway": a,
        "htHome": ht[0] if ht else None, "htAway": ht[1] if ht else None,
        "duration": dur if dur in DURATIONS else None,
        "winner": WINNER_OF.get(score.get("winner")),
        "scorers": (entry or {}).get("scorers"),
    }


def _rows_from_payload(data, get_detail):
    """Listsvaret från football-data → resultatposter. `get_detail(m)` ger
    detaljcache-posten (eller None) för en match — injicerbar så självtestet
    kan köra hela parsningsvägen utan nät."""
    out = []
    for m in data.get("matches") or []:
        if m.get("status") not in DONE:
            continue
        home = short_of(((m.get("homeTeam") or {}).get("name")) or "")
        away = short_of(((m.get("awayTeam") or {}).get("name")) or "")
        if not (home and away):
            continue
        row = _build_row(m, home, away, get_detail(m))
        if row:
            out.append(row)
    return out


def from_football_data(token):
    data = _fetch(FOOTBALLDATA_URL, headers={"X-Auth-Token": token, "Accept": "application/json"})
    cache = _load_cache()
    dirty = False

    def get_detail(m):
        # Detaljanrop bara för NYA färdigspelade matcher — cachen gör att
        # redan hämtade matcher aldrig hämtas om (filen committas i repot).
        nonlocal dirty
        mid = m.get("id")
        if mid is None:
            return None
        key = str(mid)
        if key in cache:
            return cache[key]
        entry = _fetch_detail_entry(token, mid)
        if entry is not None:
            cache[key] = entry
            dirty = True
        return entry

    out = _rows_from_payload(data, get_detail)
    if dirty:
        _save_cache(cache)
    return out


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


def from_facit():
    """Tokenfri reserv — ger bara slutresultat, de berikade fälten blir null."""
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
                    "scoreHome": int(score[0]), "scoreAway": int(score[1]),
                    "htHome": None, "htAway": None,
                    "duration": None, "winner": None, "scorers": None})
    return out


def build_progress(results):
    """Resultatposterna → progress-dicten för turneringsmarknaderna.

    {"topp16": {"qualified": [...], "eliminated": [...]}, "topp8": ..., ...}

    qualified[steg] = lag som klarat marknaden (topp16 = vann sin sextondels-
    final osv; vinnare = vann finalen). eliminated[steg] = lag som definitivt
    missat den: förlorarna i stegets spelade matcher, PLUS — när steget är
    komplett (alla matcher avgjorda) — alla 48 lag som inte är qualified.
    Kaskad: lag eliminerade i ett steg är per definition eliminerade i alla
    senare steg. Avancemanget avgörs av winner-fältet (täcker straffläggning);
    poster utan winner eller utan date hoppas över tills nästa körning.
    """
    all_teams = {t[1] for t in TEAMS}
    by_market = {key: [] for _st, key, _n in KNOCKOUT_MARKETS}
    market_of_stage = {st: key for st, key, _n in KNOCKOUT_MARKETS}
    for r in results or []:
        d = r.get("date")
        if not d:
            continue  # utan datum kan steget inte fastställas (facit-reserven)
        key = market_of_stage.get(stage_for(r.get("home"), r.get("away"), d))
        if key:
            by_market[key].append(r)

    progress = {}
    carried = set()  # eliminerade i tidigare steg — kaskaderar framåt
    for _stage, key, expected in KNOCKOUT_MARKETS:
        qualified, losers = [], []
        for r in by_market[key]:
            w = r.get("winner")
            if w == "home":
                win, lose = r["home"], r["away"]
            elif w == "away":
                win, lose = r["away"], r["home"]
            else:
                continue  # winner saknas — kan inte avgöras än
            qualified.append(win)
            losers.append(lose)
        q = set(qualified)
        eliminated = set(losers) | carried
        if len(q) == expected:
            # Steget komplett: alla som inte gick vidare har definitivt
            # missat marknaden — även lag som åkte ut före steget.
            eliminated |= all_teams - q
        eliminated -= q
        progress[key] = {"qualified": sorted(q), "eliminated": sorted(eliminated)}
        carried = eliminated
    return progress


def fetch_results():
    """-> (results, progress). progress är alltid komplett (tomma listor
    innan slutspelet) så appen kan avkoda den ovillkorligt."""
    token = (os.environ.get("FOOTBALLDATA_TOKEN") or "").strip()
    results = None
    if token:
        try:
            results = from_football_data(token)
            print("  resultat: %d färdigspelade via football-data.org" % len(results))
        except Exception as e:
            print("  ! football-data.org failade: %s — provar facit-reserven" % e, file=sys.stderr)
    if results is None:
        try:
            results = from_facit()
            print("  resultat: %d färdigspelade via vm2026-facit (reserv)" % len(results))
        except Exception as e:
            print("  ! facit-reserven failade också: %s" % e, file=sys.stderr)
            results = []
    progress = build_progress(results)
    decided = sum(len(progress[k]["qualified"]) for k in progress)
    if decided:
        print("  progress: %d slutspelsavancemang avgjorda" % decided)
    return results, progress


# ---------------------------------------------------------------------------
# Självtest — körs HELT utan nät med syntetiska football-data-svar.
# ---------------------------------------------------------------------------

def _selftest():
    # (a) Förlängningsmatch: 90-minutersresultatet (regularTime) ska användas
    #     för scoreHome/Away — INTE fullTime som inkluderar förlängningen.
    fake_et = {
        "id": 9001, "status": "FINISHED", "utcDate": "2026-07-04T20:00:00Z",
        "homeTeam": {"name": "Sweden"}, "awayTeam": {"name": "Croatia"},
        "score": {"winner": "HOME_TEAM", "duration": "EXTRA_TIME",
                  "fullTime": {"home": 2, "away": 1},
                  "regularTime": {"home": 1, "away": 1},
                  "halfTime": {"home": 0, "away": 1}},
    }
    # (b) Straffmatch: oavgjort efter 90 OCH 120 — winner ska komma ur
    #     score.winner. regularTime saknas i listsvaret här: tas ur cachen.
    fake_pen = {
        "id": 9002, "status": "FINISHED", "utcDate": "2026-07-09T20:00:00Z",
        "homeTeam": {"name": "Spain"}, "awayTeam": {"name": "Argentina"},
        "score": {"winner": "AWAY_TEAM", "duration": "PENALTY_SHOOTOUT",
                  "fullTime": {"home": 2, "away": 2},
                  "halfTime": {"home": 1, "away": 0}},
    }
    # Vanlig gruppmatch med cachad scorers-post.
    fake_reg = {
        "id": 9003, "status": "FINISHED", "utcDate": "2026-06-11T19:00:00Z",
        "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
        "score": {"winner": "HOME_TEAM", "duration": "REGULAR",
                  "fullTime": {"home": 2, "away": 0},
                  "halfTime": {"home": 1, "away": 0}},
    }
    details = {
        9002: {"scorers": None, "ht": [1, 0], "regular": [1, 1],
               "duration": "PENALTY_SHOOTOUT", "winner": "AWAY_TEAM"},
        9003: {"scorers": [{"name": "Raúl Jiménez", "team": "Mexiko", "goals": 2}],
               "ht": [1, 0], "regular": [2, 0],
               "duration": "REGULAR", "winner": "HOME_TEAM"},
    }
    rows = _rows_from_payload({"matches": [fake_et, fake_pen, fake_reg]},
                              lambda m: details.get(m.get("id")))
    assert len(rows) == 3, rows
    et, pen, reg = rows

    # (a) förlängning
    assert et["home"] == "Sverige" and et["away"] == "Kroatien"
    assert (et["scoreHome"], et["scoreAway"]) == (1, 1), "regularTime ska användas vid förlängning"
    assert et["duration"] == "EXTRA_TIME" and et["winner"] == "home"
    assert (et["htHome"], et["htAway"]) == (0, 1)
    assert et["scorers"] is None  # detaljanropet "failade" (ingen cachepost)

    # (b) straffar
    assert (pen["scoreHome"], pen["scoreAway"]) == (1, 1), "regularTime ur cachen vid straffar"
    assert pen["winner"] == "away", "winner ur score.winner trots oavgjort i 90"
    assert pen["duration"] == "PENALTY_SHOOTOUT"

    # (c) scorers-aggregering: 2 mål (varav en vanlig straff) av samma
    #     spelare → goals: 2; självmål exkluderat.
    goals = [
        {"minute": 10, "type": "REGULAR", "team": {"name": "Mexico"},
         "scorer": {"name": "Raúl Jiménez"}},
        {"minute": 55, "type": "PENALTY", "team": {"name": "Mexico"},
         "scorer": {"name": "Raúl Jiménez"}},
        {"minute": 70, "type": "OWN", "team": {"name": "Mexico"},
         "scorer": {"name": "Egen Målsson"}},
    ]
    agg = _aggregate_scorers(goals)
    assert agg == [{"name": "Raúl Jiménez", "team": "Mexiko", "goals": 2}], agg
    assert reg["scorers"] == agg

    # (d) build_progress: 16 syntetiska sextondelsfinaler (kors-grupp-par så
    #     stage_for ger "Sextondelsfinal", hemmalaget vinner alla).
    shorts = [t[1] for t in TEAMS]
    pairs = []
    for blk in range(0, 48, 8):  # (A,B), (C,D), ... — aldrig samma grupp
        for i in range(4):
            pairs.append((shorts[blk + i], shorts[blk + 4 + i]))
    pairs = pairs[:16]  # 32 unika lag
    r32 = [{"date": "2026-07-01", "home": h, "away": a,
            "scoreHome": 1, "scoreAway": 0, "winner": "home"} for h, a in pairs]

    prog = build_progress(r32)
    assert set(prog) == {"topp16", "topp8", "topp4", "topp2", "vinnare"}
    assert len(prog["topp16"]["qualified"]) == 16
    assert set(prog["topp16"]["qualified"]) == {h for h, _a in pairs}
    assert len(prog["topp16"]["eliminated"]) == 32, "komplett steg: 48-16 eliminerade"
    assert len(prog["topp8"]["eliminated"]) == 32, "kaskaden ska fylla topp8"
    assert len(prog["vinnare"]["eliminated"]) == 32, "kaskaden ska nå vinnare"
    assert prog["topp8"]["qualified"] == []

    # Bara 3 spelade sextondelsfinaler: eliminated = exakt de 3 förlorarna.
    prog3 = build_progress(r32[:3])
    assert prog3["topp16"]["qualified"] == sorted(h for h, _a in pairs[:3])
    assert prog3["topp16"]["eliminated"] == sorted(a for _h, a in pairs[:3])
    assert prog3["topp8"]["eliminated"] == sorted(a for _h, a in pairs[:3]), "kaskad"

    # (e) Cache-posten ur detaljsvaret: en förlängningsmatch utan regularTime
    #     får INTE cachas (annars kan 90-minutersresultatet låsas ute för
    #     alltid), medan en komplett ET-detalj och en vanlig match utan
    #     regularTime cachas som vanligt.
    det_ok = {"goals": goals[:1],
              "score": {"winner": "HOME_TEAM", "duration": "EXTRA_TIME",
                        "fullTime": {"home": 2, "away": 1},
                        "regularTime": {"home": 1, "away": 1},
                        "halfTime": {"home": 0, "away": 1}}}
    e_ok = _entry_from_detail(det_ok)
    assert e_ok and e_ok["regular"] == [1, 1] and e_ok["duration"] == "EXTRA_TIME"
    det_bad = {"goals": [], "score": {"winner": "HOME_TEAM", "duration": "EXTRA_TIME",
                                      "fullTime": {"home": 2, "away": 1}}}
    assert _entry_from_detail(det_bad) is None, "ET-detalj utan regularTime får inte cachas"
    det_reg = {"goals": [], "score": {"winner": "DRAW", "duration": "REGULAR",
                                      "fullTime": {"home": 0, "away": 0}}}
    assert _entry_from_detail(det_reg) is not None, "REGULAR utan regularTime är ok"
    assert _entry_from_detail({"score": {}}) is None, "saknade goals[] cachas inte"

    # Tomt resultat → komplett men tom progress-struktur.
    empty = build_progress([])
    assert all(empty[k] == {"qualified": [], "eliminated": []} for k in empty)

    # Facit-reserven: poster utan date ska hoppas över i progress.
    facit_row = {"date": None, "home": "Mexiko", "away": "Sydafrika",
                 "scoreHome": 2, "scoreAway": 0, "htHome": None, "htAway": None,
                 "duration": None, "winner": None, "scorers": None}
    nul = build_progress([facit_row])
    assert all(nul[k] == {"qualified": [], "eliminated": []} for k in nul)

    print("SELFTEST OK — förlängning, straffar, scorers och progress beter sig rätt.")


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        _selftest()
        sys.exit(0)
    res, prog = fetch_results()
    for r in res:
        print(r)
    print(json.dumps(prog, ensure_ascii=False))
