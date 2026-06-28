#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Matchmodellen — samma analysmetod som hemsidan (Oscars funderingar).

Lagstyrka:
  • Live-Elo från eloratings.net (uppdateras efter varje matchdag — det är
    så "nya analyser varje morgon" får in turneringens faktiska resultat).
  • Fryst MSS (mss.json från vm2026-facit-repot, frysningen 11 juni) som
    prior: MSS mappas till Elo-skalan och blandas med live-Elo — 30 % i
    gruppspel, 20 % i slutspel (då gruppformen redan bärs av live-Elo).
  • Värdnationerna (USA/Mexiko/Kanada) får +60 Elo — de spelar alla sina
    matcher på hemmaplan (Källor & Metod: eloratings traditionellt +100
    för äkta hemmaplan; VM-publik är mer blandad → försiktigare nudge).

Matchsannolikheter:
  Elo-diff → förväntad målskillnad, total-mål-baslinje 2.75 i gruppspel och
  2.50 i slutspel (slutspel scorar lägre i ordinarie tid). Poisson-rutnät
  0–10 mål med Dixon-Coles-justering (ρ=−0.08) som ger 1X2, Över/Under
  valfri linje och Båda lagen gör mål — konsekvent ur samma rutnät. Modellen
  krymps 70/30 mot avvigade marknadspriser innan edge räknas (ödmjukhet:
  marknaden bär information modellen saknar). Slutspelsmatcher får dessutom
  ett avancemang (p_progress): 90 min → förlängning → straffar.
"""
import csv
import io
import json
import math
import sys
import urllib.request

from wc_data import TEAMS, SHORT_FROM_ELO, HOSTS, ELO_CODE2SHORT, short_of

ELO_NOW_URL = "https://www.eloratings.net/World.tsv"
ELO_MIN, ELO_MAX = 1000.0, 2400.0
MSS_FROZEN_URL = "https://raw.githubusercontent.com/oscarsteinconsulting/vm2026-facit/main/mss.json"

# Mål-baslinjer. Gruppspelet 2026 gav 2.99 mål/match; modellens gamla 2.60
# underskattade systematiskt (~+15 %). MU_TOTAL höjs till 2.75 via en empirisk-
# Bayes-blandning av turneringsbeviset (2.99, n=72) med en historisk VM-grupp-
# prior (~2.6, n_prior≈40): (2.62·40 + 2.986·72)/112 ≈ 2.86, nedtonad till 2.75
# för att INTE overfit:a ett enda VM. Slutspelet scorar historiskt LÄGRE i
# ordinarie tid (tightare fält när svaga lag är ute; publicerade KO-snitt är
# dessutom förlängnings-inflaterade) → en egen, lägre KO-baslinje 2.50.
MU_TOTAL = 2.75         # förväntade totalmål, gruppspel/default
KO_MU_TOTAL = 2.50      # förväntade totalmål, slutspel (90 min) — medvetet < grupp
# Styrke→mål-känslighet. Kalibreringen visade UNDER-dispersion (starka lag gjorde
# fler mål än väntat, svaga släppte in fler) och favorit-underskattning. En lägre
# ELO_PER_GOAL vidgar λ-spridningen per Elo-enhet. Flytten 270→250 (~7 %) är
# medvetet måttlig: den naiva gruppspelssignalen (~190) är uppblåst av blowouts
# mot svaga lag som inte återkommer i det tightare slutspelet.
ELO_PER_GOAL = 250.0    # Elo-diff som motsvarar 1.0 i förväntad målskillnad
HOST_ELO_BONUS = 60.0
MSS_BLEND = 0.30        # andel fryst MSS i den effektiva ratingen (gruppspel)
# Slutspel: den frysta MSS-priorn (11 juni) är nu äldre och gruppspelets info
# bärs redan av live-Elo → lägre MSS-vikt i slutspelet (mer vikt på färsk form).
KO_MSS_BLEND = 0.20
DC_RHO = -0.08          # Dixon-Coles lågmålskorrelation
SHRINK_MODEL = 0.70     # p_used = 0.70·modell + 0.30·avvigad marknad

# Slutspelsdynamik (förlängning + straffar) — används bara av p_progress() och
# turneringssimuleringen, ALDRIG av 90-min-marknaderna (1X2/OU/BTTS/…).
ET_DURATION_SHARE = 30.0 / 90.0   # förlängning = 1/3 av ordinarie speltid
ET_TEMPO = 0.85                   # lägre tempo/mer slutet spel i förlängningen
PEN_BASE = 0.50                   # straffläggning ≈ slantsingling
PEN_TILT = 0.10                   # MAX favorit-tilt i straffar (hårt clampad)
PEN_TILT_ELO = 600.0             # Elo-diff för fullt tilt-utslag

MAX_GOALS = 10
MAX_GOALS_HALF = 7      # räcker gott för en halvlek — och håller HT/FT snabb

# Empirisk målfördelning över halvlekarna: ~44 % av målen görs i första
# halvlek, ~56 % i andra (lägre tempo tidigt, öppnare och tröttare sent).
HALF_SHARE = {1: 0.44, 2: 0.56}


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (stakbrons-vm-feed)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_live_elo():
    """{kortnamn: rating} från eloratings.net — samma heuristiska parser
    som mss_update.py (lagnamn + tal i rimligt Elo-spann per rad)."""
    raw = _fetch(ELO_NOW_URL)
    out = {}
    for row in csv.reader(io.StringIO(raw), delimiter="\t"):
        if not row:
            continue
        short, rating = None, None
        for cell in row:
            c = cell.strip()
            if short is None:
                # World.tsv använder 2-bokstavskoder; namnvarianter som reserv
                short = ELO_CODE2SHORT.get(c) or short_of(c)
            elif rating is None:
                # ratingen är första rimliga Elo-talet EFTER lagkoden
                try:
                    v = float(c.replace("−", "-"))
                except ValueError:
                    continue
                if ELO_MIN <= v <= ELO_MAX:
                    rating = v
        if short and rating is not None and short not in out:
            out[short] = rating
    return out


def fetch_frozen_mss():
    """{kortnamn: {mss, elo_now}} ur den frysta prognosen i facit-repot."""
    data = json.loads(_fetch(MSS_FROZEN_URL))
    out = {}
    for elo_name, row in (data.get("teams") or {}).items():
        short = SHORT_FROM_ELO.get(elo_name) or short_of(elo_name)
        if short:
            out[short] = {"mss": float(row.get("mss", 50.0)),
                          "elo": float(row.get("elo_now", 0.0)) or None}
    return out


_FETCH_CACHE = {}   # memoiserar live-Elo + fryst MSS så flera blend-anrop per
                    # körning (grupp + slutspel) inte hämtar om nätet i onödan.


def _fetch_sources():
    if "live" not in _FETCH_CACHE:
        try:
            _FETCH_CACHE["live"] = fetch_live_elo()
        except Exception as e:
            print("  ! live-Elo failade: %s" % e, file=sys.stderr)
            _FETCH_CACHE["live"] = {}
        try:
            _FETCH_CACHE["mss"] = fetch_frozen_mss()
        except Exception as e:
            print("  ! fryst MSS failade: %s" % e, file=sys.stderr)
            _FETCH_CACHE["mss"] = {}
    return _FETCH_CACHE["live"], _FETCH_CACHE["mss"]


def build_ratings(blend=MSS_BLEND):
    """Effektiv rating per lag = (1−blend)·live-Elo + blend·(MSS→Elo-skalan).

    `blend` är andelen fryst MSS (default MSS_BLEND=0.30 för gruppspel; slutspel
    använder KO_MSS_BLEND=0.20 för mer vikt på färsk live-form). Källhämtningen
    cachas så grupp- och slutspels-ratingset kan byggas utan dubbla nätanrop.
    Returnerar (ratings, mss_map, elo_source) där elo_source är "live"/"frozen".
    """
    live, mss = _fetch_sources()

    shorts = [t[1] for t in TEAMS]
    elo_source = "live" if len(live) >= 40 else "frozen"
    base = {}
    for s in shorts:
        v = live.get(s)
        if v is None:
            v = (mss.get(s) or {}).get("elo")
        if v is None:
            v = 1600.0
        base[s] = v

    lo, hi = min(base.values()), max(base.values())
    span = max(1.0, hi - lo)
    ratings = {}
    for s in shorts:
        m = (mss.get(s) or {}).get("mss")
        if m is None:
            ratings[s] = base[s]
        else:
            elo_from_mss = lo + (m / 100.0) * span
            ratings[s] = (1.0 - blend) * base[s] + blend * elo_from_mss
    mss_map = {s: (mss.get(s) or {}).get("mss") for s in shorts}
    return ratings, mss_map, elo_source


# ---------------------------------------------------------------------------
# Poisson-rutnätet
# ---------------------------------------------------------------------------

def _pois(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def score_grid(lam_h, lam_a, max_goals=MAX_GOALS):
    """P(h, a) för 0–max_goals mål per lag, Dixon-Coles-justerad och renormaliserad."""
    g = [[_pois(lam_h, h) * _pois(lam_a, a) for a in range(max_goals + 1)]
         for h in range(max_goals + 1)]
    r = DC_RHO
    g[0][0] *= 1.0 - lam_h * lam_a * r
    g[0][1] *= 1.0 + lam_h * r
    g[1][0] *= 1.0 + lam_a * r
    g[1][1] *= 1.0 - r
    tot = sum(sum(row) for row in g)
    return [[p / tot for p in row] for row in g]


class MatchModel:
    """Sannolikheter för en match, härledda ur ett gemensamt målrutnät."""

    def __init__(self, home, away, ratings, mu_total=MU_TOTAL):
        d = ratings[home] - ratings[away]
        if home in HOSTS:
            d += HOST_ELO_BONUS
        if away in HOSTS:
            d -= HOST_ELO_BONUS
        self._elo_diff = d        # host-justerad Elo-diff (för straff-tilten)
        delta = max(-2.2, min(2.2, d / ELO_PER_GOAL))
        # mu_total väljs av anroparen: MU_TOTAL för gruppspel, KO_MU_TOTAL för
        # slutspel (generate.py/tournament.py sätter det per match via fas).
        self.lam_h = max(0.15, mu_total / 2.0 + delta / 2.0)
        self.lam_a = max(0.15, mu_total / 2.0 - delta / 2.0)
        self.grid = score_grid(self.lam_h, self.lam_a)
        self._half_grids = {}

    def p_1x2(self):
        ph = sum(self.grid[h][a] for h in range(MAX_GOALS + 1) for a in range(MAX_GOALS + 1) if h > a)
        pd = sum(self.grid[h][h] for h in range(MAX_GOALS + 1))
        return ph, pd, 1.0 - ph - pd

    def p_over(self, line):
        return sum(p for h, row in enumerate(self.grid) for a, p in enumerate(row) if h + a > line)

    def p_btts(self):
        return sum(p for h, row in enumerate(self.grid) for a, p in enumerate(row) if h >= 1 and a >= 1)

    def lam_total(self):
        return self.lam_h + self.lam_a

    def p_double_chance(self):
        """(p1X, p12, pX2) — direkt ur 1X2-sannolikheterna."""
        ph, pd, pa = self.p_1x2()
        return ph + pd, ph + pa, pd + pa

    def p_advance_if_drawn(self):
        """P(hemmalaget går vidare | oavgjort efter 90 min): förlängning (λ
        skalad ~30/90 med lägre tempo) → vid fortsatt lika straffar (≈50/50 med
        svag, hårt clampad favorit-tilt). Delas av p_progress OCH turneringssimen
        så feedkortets pAdvance och outright-priserna bygger på SAMMA KO-modell."""
        lh = self.lam_h * ET_DURATION_SHARE * ET_TEMPO
        la = self.lam_a * ET_DURATION_SHARE * ET_TEMPO
        g = score_grid(lh, la, MAX_GOALS_HALF)       # förlängningsrutnät (litet λ)
        n = len(g)
        eh = sum(g[h][a] for h in range(n) for a in range(n) if h > a)
        ed = sum(g[h][h] for h in range(n))          # fortf. lika → straffar
        tilt = max(-1.0, min(1.0, self._elo_diff / PEN_TILT_ELO))
        pen = max(0.30, min(0.70, PEN_BASE + PEN_TILT * tilt))
        return eh + ed * pen

    def p_progress(self):
        """P(hemmalaget går vidare) i en slutspelsmatch: vinst på 90 min, eller
        oavgjort 90 → vidare via förlängning/straffar. Påverkar INTE 90-min-
        marknaderna. Symmetrisk: hemmalagets + bortalagets avancemang = 1.
        """
        ph, pd, pa = self.p_1x2()                    # 90 min
        return ph + pd * self.p_advance_if_drawn()

    def p_handicap(self, line):
        """P(hemmalaget täcker handikappet) för en HALVLINJE (t.ex. −1.5,
        −0.5, +0.5): summan av rutnätet där h + line > a. Halvlinjer kan
        aldrig sluta push — därför hanteras inga hel-/kvartslinjer."""
        return sum(p for h, row in enumerate(self.grid)
                   for a, p in enumerate(row) if h + line > a)

    def p_score(self, h, a):
        """P(exakt resultat h–a) ur rutnätet (0 utanför 0–10)."""
        if 0 <= h <= MAX_GOALS and 0 <= a <= MAX_GOALS:
            return self.grid[h][a]
        return 0.0

    def half_grid(self, which):
        """Målrutnät för halvlek 1 eller 2: λ skalas med den empiriska
        målandelen (44 % första, 56 % andra — se HALF_SHARE). Cachas."""
        g = self._half_grids.get(which)
        if g is None:
            share = HALF_SHARE[which]
            g = score_grid(self.lam_h * share, self.lam_a * share, MAX_GOALS_HALF)
            self._half_grids[which] = g
        return g

    def p_1x2_first_half(self):
        g = self.half_grid(1)
        n = len(g)
        ph = sum(g[h][a] for h in range(n) for a in range(n) if h > a)
        pd = sum(g[h][h] for h in range(n))
        return ph, pd, 1.0 - ph - pd

    def p_over_first_half(self, line):
        g = self.half_grid(1)
        return sum(p for h, row in enumerate(g) for a, p in enumerate(row) if h + a > line)

    def p_btts_first_half(self):
        g = self.half_grid(1)
        return sum(p for h, row in enumerate(g) for a, p in enumerate(row) if h >= 1 and a >= 1)

    def p_htft(self):
        """Halvtid/Fulltid: {"1/1", "1/X", ..., "2/2"} ur produkten av de
        två halvleksrutnäten — HT-utfall ur (h1, a1), FT ur (h1+h2, a1+a2)."""
        g1, g2 = self.half_grid(1), self.half_grid(2)
        n = len(g1)
        out = {"%s/%s" % (a, b): 0.0 for a in "1X2" for b in "1X2"}
        for h1 in range(n):
            for a1 in range(n):
                p1 = g1[h1][a1]
                if p1 < 1e-12:
                    continue
                ht = "1" if h1 > a1 else ("X" if h1 == a1 else "2")
                for h2 in range(n):
                    for a2 in range(n):
                        hf, af = h1 + h2, a1 + a2
                        ft = "1" if hf > af else ("X" if hf == af else "2")
                        out[ht + "/" + ft] += p1 * g2[h2][a2]
        return out

    @staticmethod
    def p_team_over(lam_team, line):
        """Poisson-svans: P(lagets mål > line) för en halvlinje — för
        lagmålsmarknaden (och hörnor, som saknar egen modell)."""
        k_max = int(math.floor(line))
        return 1.0 - sum(_pois(lam_team, k) for k in range(k_max + 1))


# ---------------------------------------------------------------------------
# Marknadshjälpare
# ---------------------------------------------------------------------------

def devig(odds_list):
    """Avviga en komplett marknad (t.ex. 1X2): implicita sannolikheter
    normaliserade till 1. None-odds ger None tillbaka."""
    if not odds_list or any(o is None or o <= 1.0 for o in odds_list):
        return None
    inv = [1.0 / o for o in odds_list]
    s = sum(inv)
    return [p / s for p in inv]


def shrink(p_model, p_market, odds=None):
    """Krymp modellen mot avvigad marknad (ödmjukhetsfaktorn).

    Vid höga odds litar vi MINDRE på modellen: favorit/longshot-bias gör att
    modellfel förstoras i svansarna (en +26%-edge på odds 9.50 är nästan
    alltid modellbrus, inte värde). Modellvikten trappas från 0.70 vid
    odds ≤ 4 ned till som lägst 0.40."""
    if p_market is None:
        return p_model
    w = SHRINK_MODEL
    if odds is not None and odds > 4.0:
        w = max(0.40, SHRINK_MODEL - 0.05 * (odds - 4.0))
    return w * p_model + (1.0 - w) * p_market


def implied_lambda_total(p_over, line):
    """Lös λ_total ur en avvigad Över-sannolikhet för given linje (bisektion).
    Antar 50/50-delning mellan lagen — räcker för total-mål-nivån."""
    if p_over is None or not (0.02 < p_over < 0.98):
        return None
    lo, hi = 0.3, 7.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        g = score_grid(mid / 2.0, mid / 2.0)
        p = sum(q for h, row in enumerate(g) for a, q in enumerate(row) if h + a > line)
        if p < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
