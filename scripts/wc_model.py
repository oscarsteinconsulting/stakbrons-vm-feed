#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Matchmodellen — samma analysmetod som hemsidan (Oscars funderingar).

Lagstyrka:
  • Live-Elo från eloratings.net (uppdateras efter varje matchdag — det är
    så "nya analyser varje morgon" får in turneringens faktiska resultat).
  • Fryst MSS (mss.json från vm2026-facit-repot, frysningen 11 juni) som
    prior: MSS mappas till Elo-skalan och blandas 30/70 med live-Elo.
  • Värdnationerna (USA/Mexiko/Kanada) får +60 Elo — de spelar alla sina
    matcher på hemmaplan (Källor & Metod: eloratings traditionellt +100
    för äkta hemmaplan; VM-publik är mer blandad → försiktigare nudge).

Matchsannolikheter:
  Elo-diff → förväntad målskillnad, total-mål-baslinje 2.6 (VM-snitt),
  Poisson-rutnät 0–10 mål med Dixon-Coles-justering (ρ=−0.08) som ger
  1X2, Över/Under valfri linje och Båda lagen gör mål — konsekvent ur
  samma rutnät. Modellen krymps 70/30 mot avvigade marknadspriser innan
  edge räknas (ödmjukhet: marknaden bär information modellen saknar).
"""
import csv
import io
import json
import math
import sys
import urllib.request

from wc_data import TEAMS, ELO_NAME_OF, SHORT_FROM_ELO, HOSTS, ELO_CODE2SHORT, short_of

ELO_NOW_URL = "https://www.eloratings.net/World.tsv"
ELO_MIN, ELO_MAX = 1000.0, 2400.0
MSS_FROZEN_URL = "https://raw.githubusercontent.com/oscarsteinconsulting/vm2026-facit/main/mss.json"

MU_TOTAL = 2.6          # förväntade mål totalt i en jämn VM-match
ELO_PER_GOAL = 270.0    # Elo-diff som motsvarar 1.0 i förväntad målskillnad
HOST_ELO_BONUS = 60.0
MSS_BLEND = 0.30        # andel fryst MSS i den effektiva ratingen
DC_RHO = -0.08          # Dixon-Coles lågmålskorrelation
SHRINK_MODEL = 0.70     # p_used = 0.70·modell + 0.30·avvigad marknad
MAX_GOALS = 10


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


def build_ratings():
    """Effektiv rating per lag = 0.70·live-Elo + 0.30·(MSS mappad till Elo-skalan).

    Returnerar (ratings, mss_map, elo_source) där elo_source är "live" eller
    "frozen" beroende på om eloratings.net gick att nå.
    """
    try:
        live = fetch_live_elo()
    except Exception as e:
        print("  ! live-Elo failade: %s" % e, file=sys.stderr)
        live = {}
    try:
        mss = fetch_frozen_mss()
    except Exception as e:
        print("  ! fryst MSS failade: %s" % e, file=sys.stderr)
        mss = {}

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
            ratings[s] = (1.0 - MSS_BLEND) * base[s] + MSS_BLEND * elo_from_mss
    mss_map = {s: (mss.get(s) or {}).get("mss") for s in shorts}
    return ratings, mss_map, elo_source


# ---------------------------------------------------------------------------
# Poisson-rutnätet
# ---------------------------------------------------------------------------

def _pois(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def score_grid(lam_h, lam_a):
    """P(h, a) för 0–10 mål per lag, Dixon-Coles-justerad och renormaliserad."""
    g = [[_pois(lam_h, h) * _pois(lam_a, a) for a in range(MAX_GOALS + 1)]
         for h in range(MAX_GOALS + 1)]
    r = DC_RHO
    g[0][0] *= 1.0 - lam_h * lam_a * r
    g[0][1] *= 1.0 + lam_h * r
    g[1][0] *= 1.0 + lam_a * r
    g[1][1] *= 1.0 - r
    tot = sum(sum(row) for row in g)
    return [[p / tot for p in row] for row in g]


class MatchModel:
    """Sannolikheter för en match, härledda ur ett gemensamt målrutnät."""

    def __init__(self, home, away, ratings):
        d = ratings[home] - ratings[away]
        if home in HOSTS:
            d += HOST_ELO_BONUS
        if away in HOSTS:
            d -= HOST_ELO_BONUS
        delta = max(-2.2, min(2.2, d / ELO_PER_GOAL))
        self.lam_h = max(0.15, MU_TOTAL / 2.0 + delta / 2.0)
        self.lam_a = max(0.15, MU_TOTAL / 2.0 - delta / 2.0)
        self.grid = score_grid(self.lam_h, self.lam_a)

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
