#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turneringssimulator för VM 2026 — outright-spelen (Slutplacering).

Två delar:
  1. Kambi: outright-eventet "VM 2026" har fem betOffers med criterion
     "Slutplacering" (Vinnare/Topp 2/Topp 4/Topp 8/Topp 16, 48 outcomes
     vardera). Implicita sannolikheter avvigas per marknad så de summerar
     till antalet platser (Vinnare→1, Topp 2→2, ... Topp 16→16).
  2. Monte Carlo: hela turneringen simuleras N gånger med matchmodellen i
     wc_model.py (Oscars funderingar). Gruppspel → tabeller → 32 lag till
     slutspel → KO-rundor till final. Per lag räknas hur ofta det når
     varje runda → pTop16/pTop8/pTop4/pTop2/pWin.

Edge per (lag, marknad): simsannolikheten krymps mot det avvigade
marknadspriset innan edge räknas. Turneringssimulering bär större
modellfel än matchmodellen (bracketen approximeras, och varje simulerad
turnering staplar 100+ matchers osäkerhet på varandra) — därför är
modellvikten här lägre än matchspelens 0.70: w = max(0.35, 0.55−0.004·odds).

Körs utan pip-paket (bara standardbiblioteket), Python 3.9+.
"""
import bisect
import datetime
import itertools
import json
import os
import random
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wc_data import TEAMS, FLAG_OF, short_of, GROUP_OF
from wc_model import MatchModel, MU_TOTAL, KO_MU_TOTAL

KAMBI_BASE = "https://eu.offering-api.kambicdn.com/offering/v2018/svenskaspel"
KAMBI_QUERY = "channel_id=1&client_id=200&lang=sv_SE&market=SE"
OUTRIGHT_EVENT_NAME = "VM 2026"
OUTRIGHT_EVENT_ID_FALLBACK = "1019275296"  # kända id:t om listan inte hittas
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605.1.15"

MATCH_ID = "vm2026-outright"
MATCH_NAME = "VM 2026"

# Värdemärkning och Kelly — identiska med generate.py
EDGE_PLAY = 0.08
EDGE_AVOID = -0.04
CHANS_ODDS = 4.0
KELLY_FRACTION = 0.25
MAX_TOP_BETS = 10
MAX_PER_TEAM_TOP = 2
MAX_PER_MARKET = 5

MIN_P_USED = 0.02     # picks under 2 % använd sannolikhet hoppas över
MAX_ODDS = 100.0      # extrema longshots prissätts för osäkert

# --- Outright-disciplin (konsistent med generate.py:s is_recommendable) ---
# Turneringssim bär större modellfel än matchmodellen (bracket-approximation +
# 100+ matchers staplad osäkerhet). En outright REKOMMENDERAS (Spelvärt/Chans,
# stakas, hamnar i "Dagens mest spelvärda") bara om alla tre villkoren håller:
#   * använd sannolikhet ≥ 10 % — under det är simbruset för stort vs signalen;
#   * odds ≤ 15.0 — samma longshot-tak som matchspelens; över det dominerar
#     longshot-marginalen och "edge" är artefakt;
#   * edge i [0.05, 0.40] — undre gränsen sållar marginalspel, den övre KAPAR
#     absurda longshot-edges (t.ex. "Ecuador topp 4 +46 %") som bara uppstår när
#     ett tunt sannolikhetsestimat möter ett högt pris.
# Runda, medvetet konservativa tal — inte fittade mot ett enskilt utfall.
OUTRIGHT_MIN_P = 0.10
OUTRIGHT_MAX_ODDS = 15.0
OUTRIGHT_EDGE_MIN = 0.05
OUTRIGHT_EDGE_MAX = 0.40


def is_recommendable_outright(p_used, odds, edge):
    """Outright-motsvarighet till generate.py:is_recommendable: rekommenderbar
    bara vid tillräcklig sannolikhetsmassa, under longshot-taket och med edge i
    rimligt spann (kapar absurda longshot-edges)."""
    if p_used < OUTRIGHT_MIN_P:
        return False
    if odds > OUTRIGHT_MAX_ODDS:
        return False
    return OUTRIGHT_EDGE_MIN <= edge <= OUTRIGHT_EDGE_MAX

# (nyckel, namn, ikon, antal platser, index i räknararrayen)
# Räknararrayen per lag är [top16, top8, top4, top2, win].
MARKETS = [
    ("vinnare", "Vinnare",                  "🏆", 1,  4),
    ("topp2",   "Topp 2 (final)",           "🥈", 2,  3),
    ("topp4",   "Topp 4 (semifinal)",       "🏅", 4,  2),
    ("topp8",   "Topp 8 (kvartsfinal)",     "🎖", 8,  1),
    ("topp16",  "Topp 16 (åttondelsfinal)", "⚽", 16, 0),
]
KAMBI_DESC2KEY = {"Vinnare": "vinnare", "Topp 2": "topp2", "Topp 4": "topp4",
                  "Topp 8": "topp8", "Topp 16": "topp16"}
DETAIL_OF = {
    "vinnare": "Vinner hela VM 2026",
    "topp2":   "Når finalen (topp 2)",
    "topp4":   "Når semifinal (topp 4)",
    "topp8":   "Når kvartsfinal (topp 8)",
    "topp16":  "Når åttondelsfinal (topp 16)",
}

# Grupperna A–L med sina fyra lag, i TEAMS-ordning
GROUPS = {}
for _g, _short, _elo, _flag in TEAMS:
    GROUPS.setdefault(_g, []).append(_short)
GROUP_ITEMS = sorted(GROUPS.items())
ALL_SHORTS = [t[1] for t in TEAMS]

# --- FIFAs FASTA slutspelsträd för VM 2026 (draglösningsoberoende topologi) ---
# Match-numren 73–88 (R32), 89–96 (R16), 97–100 (kvart), 101–102 (semi), 104
# (final) är publicerade i förväg och ändras ALDRIG. Varje R32-match har två
# slots, kodade 'W<grupp>' (gruppvinnare), 'R<grupp>' (tvåa) eller 'T' (en av de
# 8 bästa treorna). Källa: officiella VM2026-spelschemat (verifierat mot tre
# oberoende källor + Kambis live-lottning). Detta är STRUKTUR, inte en fittad
# parameter — det rättar bracket-GEOMETRIN i outright-simen (R32-vinnare paras
# enligt det riktiga trädet i stället för adjacent).
R32_SLOTS = {
    73: ("RA", "RB"), 74: ("WE", "T"),  75: ("WF", "RC"), 76: ("WC", "RF"),
    77: ("WI", "T"),  78: ("RE", "RI"), 79: ("WA", "T"),  80: ("WL", "T"),
    81: ("WD", "T"),  82: ("WG", "T"),  83: ("RK", "RL"), 84: ("WH", "RJ"),
    85: ("WB", "T"),  86: ("WJ", "RH"), 87: ("WK", "T"),  88: ("RD", "RG"),
}
# R16 (matcherna 89–96): vilka R32-match-vinnare som möts. ORDNINGEN är vald så
# att adjacent-parning av R16-vinnarlistan ger rätt bracket HELA vägen kvart →
# semi → final (FIFAs semifinaler KORSAR: SF101 = vinnare[QF97] vs vinnare[QF99],
# SF102 = vinnare[QF98] vs vinnare[QF100]). Därför läggs match 93/94 (QF99) direkt
# efter 89/90 (QF97), inte i ren match-nummer-ordning. Halva A = de 4 första R16-
# matcherna, halva B = de 4 sista (möts först i finalen). Verifierat mot
# officiella matchnr 89–102 (Wikipedia 2026 FIFA WC knockout stage).
R16_TREE = [(74, 77), (73, 75), (83, 84), (81, 82),
            (76, 78), (79, 80), (86, 88), (85, 87)]
# Ankar-slot → R32-matchnummer (T hoppas; varje par har minst ett W/R-ankare).
ANCHOR2NUM = {}
for _num, _slots in R32_SLOTS.items():
    for _s in _slots:
        if _s != "T":
            ANCHOR2NUM[_s] = _num


# ---------------------------------------------------------------------------
# DEL 1 — Kambi-odds (Slutplacering)
# ---------------------------------------------------------------------------

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
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


def fetch_outright_odds():
    """{marknadsnyckel: {kortnamn: odds}} för de fem Slutplacering-marknaderna.

    Outright-eventet hittas i competitions-listan (taggen COMPETITION och
    namnet "VM 2026"); kända id:t används som reserv om listan ändras.
    """
    url = "%s/listView/football/world_cup_2026/all/all/competitions.json?%s" % (
        KAMBI_BASE, KAMBI_QUERY)
    event_id = OUTRIGHT_EVENT_ID_FALLBACK
    try:
        data = _get(url)
        for wrapper in data.get("events", []):
            ev = wrapper.get("event") or {}
            if ("COMPETITION" in (ev.get("tags") or [])
                    and ev.get("name") == OUTRIGHT_EVENT_NAME):
                event_id = str(ev["id"])
                break
    except Exception as e:
        print("  ! competitions-listan failade (%s), provar kända id:t" % e,
              file=sys.stderr)

    detail = _get("%s/betoffer/event/%s.json?%s" % (KAMBI_BASE, event_id, KAMBI_QUERY))
    out = {}
    for bo in detail.get("betOffers", []):
        if (bo.get("criterion") or {}).get("label") != "Slutplacering":
            continue
        key = KAMBI_DESC2KEY.get(bo.get("description"))
        if not key:
            continue
        teams = {}
        for o in bo.get("outcomes", []):
            if o.get("status", "OPEN") != "OPEN":
                continue
            team = short_of(o.get("participant"))
            odds = _odds(o.get("odds"))
            if team and odds:
                teams[team] = odds
        if teams:
            out[key] = teams
    return out


def devig_outright(odds_by_team, n_places):
    """Avviga en slutplaceringsmarknad: implicita sannolikheter 1/odds
    normaliseras så de summerar till antalet platser (Topp 4 → 4 osv)."""
    inv = {t: 1.0 / o for t, o in odds_by_team.items()}
    s = sum(inv.values())
    if s <= 0:
        return {}
    return {t: min(0.999, n_places * v / s) for t, v in inv.items()}


# ---------------------------------------------------------------------------
# DEL 2 — Monte Carlo-simulering av hela turneringen
# ---------------------------------------------------------------------------

def _pair_dist(t1, t2, ratings, mu, cache):
    """Kumulativ målfördelning för paret (t1, t2), cachad kanoniskt.

    `ratings`/`mu` är fas-medvetna: gruppspel anropas med grupp-ratings +
    MU_TOTAL, slutspel med KO-ratings + KO_MU_TOTAL (separata cachar).
    Returnerar (cum, scores, p_adv_drawn, swapped):
      cum/scores — kumulativ fördelning över 11×11-rutnätet,
      p_adv_drawn — P(kanoniska lag a går vidare | oavgjort efter 90 min),
        ur SAMMA förlängning+straff-modell som feedkortets pAdvance
        (MatchModel.p_advance_if_drawn) → outright och matchkort konsistenta.
    Rutnätet är symmetriskt under lagbyte (transponat), så bara den
    lexikografiskt lägre ordningen byggs och cachas.
    """
    swapped = t1 > t2
    a, b = (t2, t1) if swapped else (t1, t2)
    d = cache.get((a, b))
    if d is None:
        model = MatchModel(a, b, ratings, mu_total=mu)
        cum, scores = [], []
        acc = 0.0
        for h, row in enumerate(model.grid):
            for aw, p in enumerate(row):
                acc += p
                cum.append(acc)
                scores.append((h, aw))
        d = (cum, scores, model.p_advance_if_drawn())
        cache[(a, b)] = d
    return d[0], d[1], d[2], swapped


def _sample_score(t1, t2, ratings, mu, cache, rng):
    """Sampla ett resultat (mål t1, mål t2) ur matchens rutnät."""
    cum, scores, _adv, swapped = _pair_dist(t1, t2, ratings, mu, cache)
    i = bisect.bisect_left(cum, rng.random())
    if i >= len(scores):
        i = len(scores) - 1
    g1, g2 = scores[i]
    return (g2, g1) if swapped else (g1, g2)


def _ko_winner(t1, t2, ratings, mu, cache, rng):
    """KO-match: 90 min ur rutnätet; vid oavgjort avgör förlängning + straffar
    via p_advance_if_drawn (samma KO-modell som feedkortets pAdvance)."""
    cum, scores, p_adv_drawn, swapped = _pair_dist(t1, t2, ratings, mu, cache)
    i = bisect.bisect_left(cum, rng.random())
    if i >= len(scores):
        i = len(scores) - 1
    g1, g2 = scores[i]
    p_adv = p_adv_drawn  # P(kanoniska a går vidare | oavgjort)
    if swapped:
        g1, g2 = g2, g1            # orientera målen till t1, t2
        p_adv = 1.0 - p_adv        # ...och avancemanget (a var t2)
    if g1 > g2:
        return t1
    if g2 > g1:
        return t2
    return t1 if rng.random() < p_adv else t2


def _draw_r32(rng, winners, runners, thirds):
    """Sextondelsfinalerna: strukturerad slumpdragning, 16 par.

    Ärlig brasklapp: FIFA:s exakta bracket (fasta positioner per grupp och
    en kombinationstabell för vilka treor som hamnar var) approximeras här
    med en slumpdragning som bevarar STRUKTUREN: 8 gruppettor möter de 8
    treorna, 4 gruppettor möter 4 grupptvåor, resterande 8 tvåor möts
    inbördes — aldrig lag ur samma grupp. Det bevarar marginal-
    sannolikheterna "når runda X", vilket är exakt det vi prissätter; den
    exakta bracketgeometrin (vem som KAN mötas i vilken kvart) modelleras
    inte. winners/runners/thirds är listor av (lag, grupp).

    Kör dragningen fast (gruppkrock), dras om — i praktiken några få varv.
    """
    for _attempt in range(1000):
        ws = list(winners)
        rng.shuffle(ws)
        ts = list(thirds)
        rng.shuffle(ts)
        rs = list(runners)
        rng.shuffle(rs)
        pairs = []
        ok = True
        # 8 ettor mot de 8 treorna (aldrig samma grupp)
        for (wt, wg), (tt, tg) in zip(ws[:8], ts):
            if wg == tg:
                ok = False
                break
            pairs.append((wt, tt))
        if not ok:
            continue
        # 4 ettor mot 4 tvåor (aldrig samma grupp)
        for (wt, wg), (rt, rg) in zip(ws[8:], rs[:4]):
            if wg == rg:
                ok = False
                break
            pairs.append((wt, rt))
        if not ok:
            continue
        # Resterande 8 tvåor möts inbördes — alla tvåor kommer ur olika
        # grupper, så gruppkrock är omöjlig här; para rakt av.
        rest = rs[4:]
        for i in range(0, 8, 2):
            pairs.append((rest[i][0], rest[i + 1][0]))
        return pairs
    # Nås i praktiken aldrig (per-försök-chansen är ~35 %); ge upp grupp-
    # villkoret hellre än att hänga.
    ws = [w for w, _g in winners]
    rs = [r for r, _g in runners]
    ts = [t for t, _g in thirds]
    pairs = list(zip(ws[:8], ts)) + list(zip(ws[8:], rs[:4]))
    rest = rs[4:]
    pairs += [(rest[i], rest[i + 1]) for i in range(0, 8, 2)]
    return pairs


def derive_real_r32(match_list, results, progress):
    """Härled de 16 VERKLIGA R32-paren när de är kända. Returnerar [(lagA, lagB),
    ...] med 16 par / 32 unika lag, eller None om data ej räcker (anroparen
    faller då tillbaka på standings-seeds eller re-simulerad slumpdragning).

    PRIMÄR: Kambis live-matchlista (redan hämtad i generate.main). En match är KO
    när lagen ej delar grupp. R32 = kors-gruppmatcher vars lag ej redan vunnit
    sin R32 (ej i progress.topp16.qualified), deduplicerat på lagpar, sorterat på
    kickoff, 16 första. Robust mot stage_for-datumglapp (kors-grupptest, ej datum)
    OCH mot stale fixtures.json (används inte alls här)."""
    qual16 = set((((progress or {}).get("topp16")) or {}).get("qualified") or [])
    try:
        seen, pairs = set(), []
        for m in sorted(match_list or [], key=lambda x: x.get("kickoff") or ""):
            h, a = m.get("home"), m.get("away")
            gh, ga = GROUP_OF.get(h), GROUP_OF.get(a)
            if not h or not a or h == a:
                continue
            if gh and gh == ga:
                continue                      # gruppmatch, ej KO
            if h in qual16 or a in qual16:
                continue                      # senare runda (laget klart R32)
            key = frozenset((h, a))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((h, a))
        flat = [t for p in pairs for t in p]
        if len(pairs) == 16 and len(set(flat)) == 32:
            return pairs
    except Exception as e:
        print("  ! R32-härledning (Kambi) failade: %s" % e, file=sys.stderr)
    return None


def standings_seeds_from_results(results):
    """Fallback: gruppettor/tvåor/bästa-treor ur facit (results) med FIFA-
    tiebreakers (poäng, målskillnad, gjorda mål). Returnerar (winners, runners,
    thirds) som listor av (lag, grupp) — formen _draw_r32 förväntar — eller None
    om någon grupp är ofullständig (lag med <3 spelade gruppmatcher)."""
    try:
        gp = {g: {t: {"pts": 0, "gf": 0, "ga": 0, "n": 0} for t in teams}
              for g, teams in GROUP_ITEMS}
        for r in results or []:
            h, a = r.get("home"), r.get("away")
            gh = GROUP_OF.get(h)
            if not gh or gh != GROUP_OF.get(a):
                continue
            sh, sa = r.get("scoreHome"), r.get("scoreAway")
            if not isinstance(sh, int) or not isinstance(sa, int):
                continue
            d = gp[gh]
            d[h]["gf"] += sh; d[h]["ga"] += sa; d[h]["n"] += 1
            d[a]["gf"] += sa; d[a]["ga"] += sh; d[a]["n"] += 1
            if sh > sa: d[h]["pts"] += 3
            elif sa > sh: d[a]["pts"] += 3
            else: d[h]["pts"] += 1; d[a]["pts"] += 1
        winners, runners, thirds_pool = [], [], []
        for g, teams in GROUP_ITEMS:
            if any(gp[g][t]["n"] < 3 for t in teams):
                return None  # gruppspelet ej färdigt → ej pålitligt
            order = sorted(teams, key=lambda t: (gp[g][t]["pts"],
                           gp[g][t]["gf"] - gp[g][t]["ga"], gp[g][t]["gf"]),
                           reverse=True)
            winners.append((order[0], g)); runners.append((order[1], g))
            s = gp[g][order[2]]
            thirds_pool.append((s["pts"], s["gf"] - s["ga"], s["gf"], order[2], g))
        thirds_pool.sort(reverse=True)
        thirds = [(row[3], row[4]) for row in thirds_pool[:8]]
        return winners, runners, thirds
    except Exception as e:
        print("  ! R32-härledning (standings) failade: %s" % e, file=sys.stderr)
        return None


def slot_map_from_seeds(seeds):
    """{lag: 'W<grupp>'/'R<grupp>'/'T'} ur seeds=(winners, runners, thirds).
    Failsafe: returnerar {} vid fel."""
    try:
        winners, runners, thirds = seeds
        sl = {}
        for t, g in winners:
            sl[t] = "W" + g
        for t, g in runners:
            sl[t] = "R" + g
        for t, _g in thirds:
            sl[t] = "T"
        return sl
    except Exception:
        return {}


def bracket_tree_from_pairs(pairs, slot_of):
    """Bind de 16 R32-paren till FIFAs fasta matchnummer via lagens slots och
    returnera (r32_pos2idx, r16_idx_pairs) — eller None om slot-upplösningen är
    ofullständig/tvetydig (anroparen faller då tillbaka på adjacent-parning).

      r32_pos2idx[k]   = index i `pairs` för R32-match (73+k), k=0..15
      r16_idx_pairs[j] = (posA, posB) in i match-nummer-ordningen för R16-match j
    """
    try:
        num2idx = {}
        for idx, (ta, tb) in enumerate(pairs):
            nums = set()
            for t in (ta, tb):
                s = slot_of.get(t)
                if s and s in ANCHOR2NUM:
                    nums.add(ANCHOR2NUM[s])
            if len(nums) != 1:
                return None                 # saknat/tvetydigt ankare
            num = nums.pop()
            if num in num2idx:
                return None                 # dubbelt matchnummer
            num2idx[num] = idx
        if set(num2idx) != set(range(73, 89)):
            return None                     # täckningsglapp
        r32_pos2idx = [num2idx[73 + k] for k in range(16)]
        r16_idx_pairs = [(na - 73, nb - 73) for na, nb in R16_TREE]
        return (r32_pos2idx, r16_idx_pairs)
    except Exception:
        return None


def simulate_tournament(ratings, ratings_ko, sims, rng, real_r32=None, seeds=None,
                        bracket=None):
    """Kör hela turneringen `sims` gånger, fas-medvetet.

    Bracketkälla (i fallande exakthet): `real_r32` (16 faktiska R32-par) →
    `seeds` (faktiska gruppseeds, strukturerad dragning) → re-simulerat gruppspel
    + slumpdragning (fallback). Oavsett källa samplas KO-utfallen per sim.

    Gruppspelet samplas med grupp-ratings + MU_TOTAL; slutspelet (R32 och
    framåt) med KO-ratings + KO_MU_TOTAL och samma förlängning/straff-modell
    som feedkortens pAdvance. Returnerar {lag: (pTop16, pTop8, pTop4, pTop2,
    pWin)} där pTop16 = sannolikheten att vinna sin sextondelsfinal osv.
    """
    counts = {s: [0, 0, 0, 0, 0] for s in ALL_SHORTS}
    cache_g = {}   # grupp-par (grupp-ratings + MU_TOTAL)
    cache_ko = {}  # slutspels-par (KO-ratings + KO_MU_TOTAL)

    for _sim in range(sims):
        if real_r32 is not None:
            pairs = real_r32                  # FAKTISKA R32-par (Kambi live)
        elif seeds is not None:
            w, r, t = seeds                   # FAKTISKA seeds (facit-standings)
            pairs = _draw_r32(rng, w, r, t)   # verkliga deltagare, strukturerad geometri
        else:
            # FALLBACK: re-simulera gruppspelet + slumpdragen R32 (oförändrat)
            winners, runners, third_cands = [], [], []
            for gname, teams in GROUP_ITEMS:
                pts = {t: 0 for t in teams}
                gf = {t: 0 for t in teams}
                ga = {t: 0 for t in teams}
                for a, b in itertools.combinations(teams, 2):
                    sa, sb = _sample_score(a, b, ratings, MU_TOTAL, cache_g, rng)
                    gf[a] += sa
                    ga[a] += sb
                    gf[b] += sb
                    ga[b] += sa
                    if sa > sb:
                        pts[a] += 3
                    elif sb > sa:
                        pts[b] += 3
                    else:
                        pts[a] += 1
                        pts[b] += 1
                order = sorted(teams,
                               key=lambda t: (pts[t], gf[t] - ga[t], gf[t], rng.random()),
                               reverse=True)
                winners.append((order[0], gname))
                runners.append((order[1], gname))
                t3 = order[2]
                third_cands.append((pts[t3], gf[t3] - ga[t3], gf[t3], rng.random(), t3, gname))
            third_cands.sort(reverse=True)
            thirds = [(row[4], row[5]) for row in third_cands[:8]]
            pairs = _draw_r32(rng, winners, runners, thirds)

        # --- Sextondelsfinal (R32) → vinnarna (i pairs-ordning) ---
        alive = [_ko_winner(a, b, ratings_ko, KO_MU_TOTAL, cache_ko, rng)
                 for a, b in pairs]
        for t in alive:
            counts[t][0] += 1  # vann sin R32-match → topp 16

        if bracket is not None:
            # FIFAs FASTA träd: para R32-vinnare enligt verkliga R16-paren, sedan
            # adjacent på den bracket-ordnade vinnarlistan (kvart/semi/final).
            r32_pos2idx, r16_idx_pairs = bracket
            w32 = [alive[i] for i in r32_pos2idx]        # match-nummer-ordning 73..88
            cur = [_ko_winner(w32[a], w32[b], ratings_ko, KO_MU_TOTAL, cache_ko, rng)
                   for a, b in r16_idx_pairs]
            for t in cur:
                counts[t][1] += 1                        # nådde topp 8
            stage = 2
            while len(cur) > 1:
                cur = [_ko_winner(cur[i], cur[i + 1], ratings_ko, KO_MU_TOTAL,
                                  cache_ko, rng)
                       for i in range(0, len(cur), 2)]
                for t in cur:
                    counts[t][stage] += 1
                stage += 1
        else:
            # FALLBACK: vinnarna paras adjacent (oförändrat ursprungsbeteende).
            stage = 1
            while len(alive) > 1:
                nxt = [_ko_winner(alive[i], alive[i + 1], ratings_ko, KO_MU_TOTAL,
                                  cache_ko, rng)
                       for i in range(0, len(alive), 2)]
                for t in nxt:
                    counts[t][stage] += 1
                alive = nxt
                stage += 1

    inv = 1.0 / float(sims)
    return {t: tuple(c * inv for c in cnt) for t, cnt in counts.items()}


# ---------------------------------------------------------------------------
# DEL 3 — edge, Bet-objekt och sektionen
# ---------------------------------------------------------------------------

def now_utc_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(s):
    # Samma som generate.py — duplicerad medvetet för att slippa importera
    # hela genereringsmodulen härifrån.
    keep = []
    for c in s.lower():
        if c.isalnum():
            keep.append(c)
        elif keep and keep[-1] != "-":
            keep.append("-")
    return "".join(keep).strip("-")[:40] or "x"


def kelly(p, odds):
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (p * b - (1.0 - p)) / b
    return max(0.0, f) * KELLY_FRACTION


def value_label(edge, odds):
    if edge >= EDGE_PLAY:
        return "Chans" if odds > CHANS_ODDS else "Spelvärt"
    if edge >= EDGE_AVOID:
        return "Neutralt"
    return "Undvik"


def _make_outright_bet(date_str, team, market_key, market_name, odds,
                       p_sim, p_mkt, sims, mss):
    """Ett Bet-objekt med exakt samma nycklar som feedens matchspel."""
    # Turneringssim har större modellfel än matchmodellen (bracket-
    # approximation + 100+ matchers staplad osäkerhet per simulering),
    # därför lägre modellvikt än matchspelens 0.70 — och ännu lägre vid
    # höga odds där longshot-bias förstorar modellfel.
    w = max(0.35, 0.55 - 0.004 * odds)
    p_used = min(0.999, w * p_sim + (1.0 - w) * p_mkt)
    edge = p_used * odds - 1.0
    rec = is_recommendable_outright(p_used, odds, edge)
    if market_key == "vinnare":
        selection = "%s vinner VM" % team
    else:
        selection = "%s topp %s" % (team, market_key.replace("topp", ""))
    mss_txt = ("%.0f" % mss) if mss is not None else "–"
    rationale = ("Simuleringen (%d turneringar) ger %.1f%% mot marknadens "
                 "%.1f%% (MSS %s). Edge %+.1f%%." % (
                     sims, p_sim * 100, p_mkt * 100, mss_txt, edge * 100))
    return {
        "id": "%s-%s-%s-%s" % (date_str, MATCH_ID, market_key, slugify(selection)),
        "matchId": MATCH_ID,
        "match": MATCH_NAME,
        "homeFlag": FLAG_OF.get(team, ""), "awayFlag": "",
        "kickoff": None,
        "categoryKey": market_key, "category": market_name,
        "selection": selection, "detail": DETAIL_OF[market_key],
        "odds": round(odds, 2),
        "modelProb": round(p_used, 4),
        "marketProb": round(p_mkt, 4),
        "edge": round(edge, 4),
        "value": value_label(edge, odds) if rec else "Neutralt",
        "recommendable": rec,
        "kelly": round(kelly(p_used, odds), 5) if rec else 0.0,
        "stakeWeight": 0.0,
        "confidence": (3 if edge >= 0.12 else 2) if rec else 0,
        "rationale": rationale,
        "settleMarket": "OUTRIGHT", "settlePick": market_key,
        "settleLine": None, "settlePlayer": team,
    }


def _build_section(probs, odds_map, mss_map, sims, date_str, progress=None):
    """Sätt ihop turneringssektionen ur simsannolikheter + Kambi-odds.

    `progress` (från results_wc.build_progress) fakta-förankrar prissättningen:
    lag vars marknadsutfall redan är AVGJORT — kvalificerade ELLER eliminerade —
    prissätts inte (simbruset på en avgjord fråga ska inte visas som värde). Det
    gör att utslagna lag inte längre får outright-edge när slutspelet rullar."""
    progress = progress or {}
    markets_out = []
    all_bets = []
    for key, name, icon, n_places, prob_idx in MARKETS:
        odds_by_team = odds_map.get(key) or {}
        mkt_probs = devig_outright(odds_by_team, n_places)
        fact = progress.get(key) or {}
        decided = set(fact.get("qualified") or []) | set(fact.get("eliminated") or [])
        bets = []
        for team, odds in odds_by_team.items():
            if odds > MAX_ODDS or team not in probs or team in decided:
                continue
            p_sim = probs[team][prob_idx]
            p_mkt = mkt_probs.get(team)
            if p_mkt is None:
                continue
            bet = _make_outright_bet(date_str, team, key, name, odds,
                                     p_sim, p_mkt, sims, mss_map.get(team))
            if bet["modelProb"] < MIN_P_USED:
                continue
            bets.append(bet)
        bets.sort(key=lambda b: -b["edge"])
        markets_out.append({"key": key, "name": name, "icon": icon,
                            "bets": bets[:MAX_PER_MARKET]})
        all_bets.extend(bets)

    # Topp 10 över alla fem marknaderna, max 2 per lag — BARA rekommenderbara
    # (samma disciplin som matchspelens rec_pool: longshot/absurd-edge-outrights
    # hamnar aldrig i "Dagens mest spelvärda").
    top_bets, per_team = [], {}
    for b in sorted((x for x in all_bets if x["recommendable"]), key=lambda b: -b["edge"]):
        team = b["settlePlayer"]
        if per_team.get(team, 0) >= MAX_PER_TEAM_TOP:
            continue
        top_bets.append(b)
        per_team[team] = per_team.get(team, 0) + 1
        if len(top_bets) >= MAX_TOP_BETS:
            break

    note = ("Monte Carlo på Oscars funderingar-modellen: hela turneringen "
            "simuleras %d gånger (slutspelsbracketen approximeras med "
            "strukturerad slumpdragning) och vägs mot avvigade Kambi-priser "
            "per slutplaceringsmarknad." % sims)
    return {
        "generatedAt": now_utc_iso(),
        "note": note,
        "topBets": top_bets,
        "markets": markets_out,
    }


def build_tournament_section(ratings, ratings_ko, mss_map, date_str, progress=None,
                             match_list=None, results=None):
    """Hela kedjan: Kambi-outrights + Monte Carlo → sektion för feeden.

    `ratings`/`ratings_ko` är grupp- resp. slutspels-ratingset (olika MSS-blend);
    simuleringen är fas-medveten. `progress` (results_wc.build_progress) fakta-
    förankrar prissättningen så avgjorda utfall inte prissätts. Returnerar None
    om oddsen inte gick att hämta (nätfel) — feeden ska kunna genereras ändå.
    """
    try:
        odds_map = fetch_outright_odds()
    except Exception as e:
        print("  ! outright-odds failade: %s" % e, file=sys.stderr)
        return None
    if not odds_map:
        print("  ! inga Slutplacering-marknader hittades", file=sys.stderr)
        return None

    sims = max(1, int(os.environ.get("VM_SIMS", "4000")))
    # Deterministisk seed per datum → samma dagsrapport vid omkörning
    rng = random.Random(int(date_str.replace("-", "")))
    # Bracketkälla (fallande exakthet): verkliga R32-par ur Kambi live →
    # gruppseeds ur facit → re-simulerad slumpdragning.
    real_r32 = derive_real_r32(match_list or [], results or [], progress)
    seeds = standings_seeds_from_results(results or []) if real_r32 is None else None
    # FIFAs fasta bracket-träd aktiveras BARA när de verkliga R32-paren är kända
    # (real_r32) — då slot-etiketterna ur facit-gruppställningen entydigt binder
    # paren till matchnumren. I seeds-/fallback-spåren dras R32 om per sim, så ett
    # fast träd ger ingen exakthetsvinst där. Säker fallback: bracket=None.
    bracket = None
    if real_r32 is not None:
        slot_of = slot_map_from_seeds(standings_seeds_from_results(results or []))
        if slot_of:
            bracket = bracket_tree_from_pairs(real_r32, slot_of)
    if real_r32 is not None:
        print("  R32: 16 verkliga par ur Kambi live | R16+: %s"
              % ("FIFA-fast bracket-träd" if bracket else "adjacent-fallback"))
    elif seeds is not None:
        print("  R32: deltagare ur facit-gruppställning (strukturerad dragning)")
    else:
        print("  R32: ingen pålitlig källa — re-simulerad slumpdragning (fallback)")
    probs = simulate_tournament(ratings, ratings_ko, sims, rng,
                                real_r32=real_r32, seeds=seeds, bracket=bracket)
    return _build_section(probs, odds_map, mss_map, sims, date_str, progress)


# ---------------------------------------------------------------------------
# Självtest — körs utan nät med syntetiska ratings och odds
# ---------------------------------------------------------------------------

BET_KEYS = ["id", "matchId", "match", "homeFlag", "awayFlag", "kickoff",
            "categoryKey", "category", "selection", "detail", "odds",
            "modelProb", "marketProb", "edge", "value", "recommendable",
            "kelly", "stakeWeight", "confidence", "rationale",
            "settleMarket", "settlePick", "settleLine", "settlePlayer"]


def _selftest():
    """Sanity-tester på simulering och bet-bygge, helt utan nätverk."""
    print("tournament.py självtest ...")
    # Syntetiska ratings: jämn stege över Elo-spannet, deterministisk
    ratings = {s: 1450.0 + 14.0 * i for i, s in enumerate(ALL_SHORTS)}
    rng = random.Random(20260611)
    sims = 400
    # Fas-medveten sim: testa med samma syntetiska ratings för grupp + KO.
    probs = simulate_tournament(ratings, ratings, sims, rng)

    s_win = sum(p[4] for p in probs.values())
    s_t16 = sum(p[0] for p in probs.values())
    assert abs(s_win - 1.0) <= 0.02, "sum(pWin)=%.4f" % s_win
    assert abs(s_t16 - 16.0) <= 0.5, "sum(pTop16)=%.4f" % s_t16
    for t, p in probs.items():
        # Monotont: nå R16 ≥ nå kvart ≥ nå semi ≥ nå final ≥ vinna
        assert p[0] >= p[1] >= p[2] >= p[3] >= p[4], "%s: %s" % (t, p)

    # Syntetiska odds ur simsannolikheterna. Faktor 1.12/fair ger ett kontrollerat
    # +12 %-edge på varje utfall (devig normaliserar bort uniform skalning), så
    # disciplin-grenarna testas på riktigt: favoriter (p≥10 %, odds≤15) blir
    # rekommenderbara, longshots (låg p / hög odds) faller utanför.
    odds_map = {}
    for key, _name, _icon, n_places, idx in MARKETS:
        teams = {}
        for t, p in probs.items():
            fair = max(p[idx], 0.003)
            teams[t] = max(1.01, min(750.0, 1.12 / fair))
        odds_map[key] = teams
    sect = _build_section(probs, odds_map, {s: 50.0 for s in ALL_SHORTS},
                          sims, "2026-06-11")

    assert len(sect["markets"]) == 5, "förväntade 5 marknader"
    assert len(sect["topBets"]) <= MAX_TOP_BETS
    for mk in sect["markets"]:
        assert len(mk["bets"]) <= MAX_PER_MARKET
    per_team = {}
    for b in sect["topBets"]:
        per_team[b["settlePlayer"]] = per_team.get(b["settlePlayer"], 0) + 1
    assert all(v <= MAX_PER_TEAM_TOP for v in per_team.values())
    for b in sect["topBets"] + [b for mk in sect["markets"] for b in mk["bets"]]:
        assert sorted(b.keys()) == sorted(BET_KEYS), "fel nycklar: %s" % sorted(b.keys())
        assert -1.0 <= b["edge"] <= 4.0, "orimlig edge: %s" % b["edge"]
        assert b["modelProb"] >= MIN_P_USED and b["odds"] <= MAX_ODDS
        assert b["settleMarket"] == "OUTRIGHT" and b["matchId"] == MATCH_ID

    # --- Outright-disciplin: rek. outrights uppfyller alla tre villkoren;
    #     icke-rek har nollställda vikter. topBets innehåller BARA rek. ---
    all_section_bets = sect["topBets"] + [b for mk in sect["markets"] for b in mk["bets"]]
    for b in all_section_bets:
        if b["recommendable"]:
            assert b["modelProb"] >= OUTRIGHT_MIN_P, b
            assert b["odds"] <= OUTRIGHT_MAX_ODDS, b
            assert OUTRIGHT_EDGE_MIN <= b["edge"] <= OUTRIGHT_EDGE_MAX, b
            assert b["value"] in ("Spelvärt", "Chans"), b
        else:
            assert b["value"] == "Neutralt", b
            assert b["kelly"] == 0.0 and b["confidence"] == 0 and b["stakeWeight"] == 0.0, b
    assert all(b["recommendable"] for b in sect["topBets"]), "topBets måste vara rek."
    assert any(b["recommendable"] for b in all_section_bets), "inga rek. outrights i selftest"

    # --- Bracket-härledning: real_r32 (Kambi) + standings (facit) ---
    shorts = [t[1] for t in TEAMS]
    ml = []
    for blk in range(0, 48, 8):           # (A vs B), (C vs D), … aldrig samma grupp
        for i in range(4):
            ml.append({"home": shorts[blk + i], "away": shorts[blk + 4 + i],
                       "kickoff": "2026-07-01T12:00:00Z"})
    ml = ml[:16]
    r32 = derive_real_r32(ml, [], {"topp16": {"qualified": [], "eliminated": []}})
    assert r32 is not None and len(r32) == 16, r32
    flat = [t for p in r32 for t in p]
    assert len(set(flat)) == 32, "R32 måste ha 32 unika lag"
    for a, b in r32:
        assert GROUP_OF[a] != GROUP_OF[b], "R32-par får ej dela grupp"
    assert derive_real_r32(ml[:10], [], {}) is None  # otillräckligt → None
    res = []
    for g, teams in GROUP_ITEMS:
        for i, j in itertools.combinations(range(4), 2):
            res.append({"home": teams[i], "away": teams[j], "scoreHome": 2, "scoreAway": 0})
    seeds = standings_seeds_from_results(res)
    assert seeds is not None
    w, rn, th = seeds
    assert len(w) == 12 and len(rn) == 12 and len(th) == 8
    s_flat = [x[0] for x in w] + [x[0] for x in rn] + [x[0] for x in th]
    assert len(set(s_flat)) == 32, "seeds måste ge 32 unika lag"
    assert standings_seeds_from_results(res[:5]) is None  # ofullständigt → None
    probs_seeded = simulate_tournament(ratings, ratings, 300, random.Random(1), real_r32=r32)
    assert abs(sum(p[4] for p in probs_seeded.values()) - 1.0) <= 0.03
    assert abs(sum(p[0] for p in probs_seeded.values()) - 16.0) <= 0.6
    for t, p in probs_seeded.items():
        assert p[0] >= p[1] >= p[2] >= p[3] >= p[4]
    in_r32 = set(flat)
    assert all(probs_seeded[t][0] == 0.0 for t in ALL_SHORTS if t not in in_r32), \
        "lag utanför verkliga R32 ska aldrig nå topp16"

    # --- FIFA-fast bracket-träd ---
    slot_of = slot_map_from_seeds(seeds)
    assert len(slot_of) == 32, "slot_of måste täcka 32 lag"
    # Bygg syntetiska R32-par enligt FIFAs slot-struktur (W/R entydiga, de 8
    # treorna fyller de 8 T-slotsen i tur) så trädet kan lösas.
    team_by_slot = {s: t for t, s in slot_of.items() if s != "T"}
    thirds_list = [t for t, _g in th]
    ti = 0
    syn_pairs = []
    for num in range(73, 89):
        sa, sb = R32_SLOTS[num]
        pa = thirds_list[ti] if sa == "T" else team_by_slot[sa]
        if sa == "T":
            ti += 1
        pb = thirds_list[ti] if sb == "T" else team_by_slot[sb]
        if sb == "T":
            ti += 1
        syn_pairs.append((pa, pb))
    in_syn = set(t for p in syn_pairs for t in p)
    assert len(in_syn) == 32, "syntetiska R32-par måste täcka 32 unika lag"
    tree = bracket_tree_from_pairs(syn_pairs, slot_of)
    assert tree is not None, "bracket_tree_from_pairs ska lösa de FIFA-strukturerade paren"
    r32_pos2idx, r16_idx_pairs = tree
    assert sorted(r32_pos2idx) == list(range(16)), "r32_pos2idx ska permutera 0..15"
    assert len(r16_idx_pairs) == 8
    # Trädet ska SKILJA sig från adjacent-parning (annars testas inget):
    adjacent = [(2 * i, 2 * i + 1) for i in range(8)]
    assert r16_idx_pairs != adjacent, "trädet ska ej vara identiskt med adjacent"
    # SEMIFINAL-TOPOLOGI: adjacent-parning av R16-vinnarlistan (kvart→semi→final)
    # måste ge FIFAs KORSANDE semifinaler. Halva A = R16-match-position 0–3, halva
    # B = 4–7; lag i A får aldrig möta lag i B före finalen. Verifierat mot
    # officiella matchnr 89–102 — vakt mot felaktig omordning av R16_TREE.
    assert set(R16_TREE[0:4]) == {(74, 77), (73, 75), (83, 84), (81, 82)}, R16_TREE
    assert set(R16_TREE[4:8]) == {(76, 78), (79, 80), (86, 88), (85, 87)}, R16_TREE
    # Deterministisk semantisk kontroll: med "starkaste laget vinner alltid" får
    # de två finalisterna komma från var sin halva (aldrig samma).
    rank = {s: i for i, s in enumerate(ALL_SHORTS)}
    w32_pos = [max(p, key=lambda t: rank[t]) for p in [syn_pairs[i] for i in r32_pos2idx]]
    r16w = [max(w32_pos[a], w32_pos[b], key=lambda t: rank[t]) for a, b in r16_idx_pairs]
    half_a = {max(r16w[0], r16w[1], key=lambda t: rank[t]),
              max(r16w[2], r16w[3], key=lambda t: rank[t])}
    half_b = {max(r16w[4], r16w[5], key=lambda t: rank[t]),
              max(r16w[6], r16w[7], key=lambda t: rank[t])}
    finalist_a = max(half_a, key=lambda t: rank[t])
    finalist_b = max(half_b, key=lambda t: rank[t])
    assert finalist_a != finalist_b, "finalisterna måste komma från olika halvor"
    # Seedad sim med träd: samma invarianter + lag utanför R32 = 0.
    probs_tree = simulate_tournament(ratings, ratings, 300, random.Random(2),
                                     real_r32=syn_pairs, bracket=tree)
    assert abs(sum(p[4] for p in probs_tree.values()) - 1.0) <= 0.03
    assert abs(sum(p[0] for p in probs_tree.values()) - 16.0) <= 0.6
    for t, p in probs_tree.items():
        assert p[0] >= p[1] >= p[2] >= p[3] >= p[4], (t, p)
    assert all(probs_tree[t][0] == 0.0 for t in ALL_SHORTS if t not in in_syn)
    # Ofullständig/tvetydig slot_of → None (fallback-grenen).
    assert bracket_tree_from_pairs(syn_pairs, {}) is None
    assert bracket_tree_from_pairs(syn_pairs, {thirds_list[0]: "WA"}) is None

    print("  OK: sum(pWin)=%.3f, sum(pTop16)=%.2f, %d marknader, %d topBets, bracket-träd OK"
          % (s_win, s_t16, len(sect["markets"]), len(sect["topBets"])))


if __name__ == "__main__":
    _selftest()
