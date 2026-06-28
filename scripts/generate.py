#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genererar data/feed.json — dagsrapporten som iOS-appen Stakbrons VM
Predictions läser, samt push-texten som send_push.py skickar kl 08:00.

Kedjan varje morgon:
  1. Lagstyrkor: live-Elo (eloratings.net) blandad med fryst MSS (hemsidans
     modell "Oscars funderingar") — se wc_model.py.
  2. Dagens matcher + Svenska Spel-odds från Kambi (kambi_wc.py).
  3. Modellsannolikhet vs avvigat marknadspris → edge per spel.
  4. Värdemärkning: Spelvärt / Chans / Neutralt / Undvik.
  5. Kvarts-Kelly-vikter för dagsbudgeten (appen räknar kronor av vikterna).
  6. Topp 10 över alla kategorier + topp 5 per Svenska Spel-kategori
     (12 kategorier som speglar Svenska Spels VM-meny).
  7. Resultat för spelade matcher (results_wc.py) → appens auto-rättning,
     plus progress-sektionen (avancemang per turneringsmarknad topp16…vinnare).
  8. Turneringssektionen (tournament.py, Monte Carlo) — failsafe-integrerad.

Körs utan pip-paket (bara standardbiblioteket), Python 3.9+.
"""
import json
import os
import sys
import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wc_data import FLAG_OF, stage_for
from wc_model import (MatchModel, build_ratings, devig, shrink,
                      implied_lambda_total, MU_TOTAL, KO_MU_TOTAL, MSS_BLEND,
                      KO_MSS_BLEND, ELO_PER_GOAL, SHRINK_MODEL)
import kambi_wc
import results_wc
import scorer_model
import tv_channels

STOCKHOLM = ZoneInfo("Europe/Stockholm")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
DAYS_DIR = os.path.join(ROOT, "data", "days")
FIXTURES_PATH = os.path.join(ROOT, "data", "fixtures.json")
CLV_PATH = os.path.join(ROOT, "data", "clv_log.json")

MODEL_VERSION = "1.2.0"   # slutspelsomkalibrering: fas-μ, dispersion, KO-dynamik

# Värdemärkning (efter krympning mot marknaden)
EDGE_PLAY = 0.08      # Spelvärt/Chans-tröskel
EDGE_AVOID = -0.04    # under detta: Undvik
CHANS_ODDS = 4.0      # över detta odds är ett positivt spel en "Chans"
KELLY_FRACTION = 0.25
MAX_TOP_BETS = 10
MAX_PER_MATCH_TOP = 3
MAX_PER_CATEGORY = 5

# Antagen enkelsidig marginal när marknaden inte kan avvigas parvis.
# Marginalen växer med oddset (longshot-marginalen är mycket större) och
# spelarmarknader över oddstaket hoppas över helt — där är prissättningen
# för osäker för att en edge ska betyda något.
MARGIN_SCORER = 1.08
MARGIN_TWOPLUS = 1.10
MARGIN_SHOTS = 1.06
PLAYER_MAX_ODDS = 15.0

# Oddstak för utfallsrika marknader (Korrekt resultat, Halvtid/Fulltid):
# över detta dominerar longshot-marginalen och en "edge" är bara brus.
SCORE_MAX_ODDS = 35.0

HTFT_KEYS = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")


def player_margin(base, odds):
    return base * (1.0 + 0.004 * odds)

# Speglar Svenska Spels VM-meny, i menyns ordning.
CATEGORIES = [
    ("fulltid", "Fulltid", "⚽"),
    ("avancemang", "Går vidare", "➡️"),
    ("dubbelchans", "Dubbelchans", "🛡"),
    ("handikapp", "Handikapp", "⚖️"),
    ("antal_mal", "Antal mål", "🥅"),
    ("btts", "Båda lagen gör mål", "🤝"),
    ("korrekt_resultat", "Korrekt resultat", "🎯"),
    ("halvlek", "Halvlek", "⏱"),
    ("halvtid_fulltid", "Halvtid/Fulltid", "🔁"),
    ("malgorare", "Målgörare", "👤"),
    ("spelarspecial", "Spelarspecial", "👟"),
    ("hornor", "Hörnor", "🚩"),
    ("kort", "Kort", "🟨"),
]


def implied_lambda_poisson(p_over, line, lo=0.5, hi=25.0):
    """Lös λ ur P(Poisson(λ) > line) = p_over (bisektion) — samma mönster
    som implied_lambda_total men ren Poisson, för marknader utan egen
    modell (hörnor)."""
    if p_over is None or not (0.02 < p_over < 0.98):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if MatchModel.p_team_over(mid, line) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def now_utc_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_kickoff(iso):
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def stockholm_matchday(kickoff_utc):
    """Matchdag = Stockholm-dygnet förskjutet -6h, så nattmatcherna i
    Nordamerika (01–05 svensk tid) räknas till kvällens spelomgång."""
    local = kickoff_utc.astimezone(STOCKHOLM)
    return (local - datetime.timedelta(hours=6)).date()


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


def confidence(edge, p, player_market):
    if player_market:
        return 3 if edge >= 0.12 else 2
    if edge >= 0.15 and p >= 0.5:
        return 5
    if edge >= 0.10:
        return 4
    if edge >= 0.06:
        return 3
    return 2


def slugify(s):
    keep = []
    for c in s.lower():
        if c.isalnum():
            keep.append(c)
        elif keep and keep[-1] != "-":
            keep.append("-")
    return "".join(keep).strip("-")[:40] or "x"


# Strategidisciplin (2026-06-21, efter halva gruppspelet). Utfallet visar att
# modellens MÅLFÖRDELNING är välkalibrerad — Dubbelchans/Antal mål/Handikapp/
# Halvlek gick klart plus — medan rakt 1X2 (−242 kr) och de OMODELLERADE
# marknaderna (hörnor/kort/målgörare/spelarspecial, bara marknadspris) gick back.
# Därför rekommenderas (Spelvärt/Chans, stakas, "Dagens mest spelvärda") bara
# marknader där modellen har bevisad edge. Övriga VISAS för överblick men
# rekommenderas aldrig:
#   - CORNERS/CARDS/PLAYER: ingen egen modell → "edge" är brus.
#   - HTFT/CS: extrem varians (9 resp. många utfall) → opålitlig edge.
#   - 1X2 över oddstaket: longshot-enskilt-utfall där modellen överskattar
#     underdog/oavgjort. Den vyn uttrycks säkrare via Dubbelchans.
# OMODELLERADE: ingen egen modell, bara marknadspris (+ antagen marginal) → en
# "edge" är ett artefakt av vår marginalgissning, inte signal. Permanent ute,
# oberoende av sample (n-oberoende prior).
UNMODELED_MARKETS = {"CORNERS", "CARDS", "PLAYER"}
# HÖGVARIANS: modell-härledda men med många utfall (9 för HT/FT, 20+ resultat),
# där longshot-marginalbruset dominerar. Rekommenderas ej. Halvlek-1X2 (1H_1X2)
# flyttades hit efter slutspelsöversynen: det är ett enskilt-utfall på lågt λ
# (en halvlek) med hög varians, och CLV-loggen visade det bland de sämsta
# marknaderna — säkrare uttryckt via halvleks-Över/Under ur samma rutnät.
HIGHVAR_MARKETS = {"HTFT", "CS", "1H_1X2"}
# ENSKILT-UTFALL: fulltids-1X2. Modellen tillverkar falsk edge på
# underdog/oavgjort i (2.5, 4.0]-bandet (shrink ger full modellvikt ända till
# odds 4.0). Den vyn uttrycks säkrare via Dubbelchans/Handikapp (samma rutnät,
# lägre varians). 2.50 är ett medvetet konservativt RUNT tal, ej fittat — i
# praktiken flaggar modellen ändå sällan ett enskilt-utfall under odds 4.0.
SINGLE_OUTCOME_MARKETS = {"1X2"}
ONE_X_TWO_MAX_ODDS = 2.50
# Går vidare (ADVANCE) är en modellerad 2-vägsmarknad (som DC/AH) → normalt
# rekommenderbar, men ett longshot-tak hindrar att ett tungt underdog-avancemang
# (där modellfelet förstoras i svansen) stakas. 2-vägs-avancemang prissätts
# sällan över ~5–6; 6.0 är ett medvetet konservativt RUNT tak, ej fittat.
ADVANCE_MAX_ODDS = 6.0


def is_recommendable(settle_market, odds):
    if settle_market in UNMODELED_MARKETS or settle_market in HIGHVAR_MARKETS:
        return False
    if settle_market in SINGLE_OUTCOME_MARKETS and odds > ONE_X_TWO_MAX_ODDS:
        return False
    if settle_market == "ADVANCE" and odds > ADVANCE_MAX_ODDS:
        return False
    return True


def is_knockout_stage(stage):
    """True för slutspelsfaser (Sextondelsfinal och framåt), False för grupp."""
    return bool(stage) and stage != "Gruppspel" and not stage.startswith("Grupp")


def build_match_model(m, ratings_group, ratings_ko):
    """MatchModel för en match med rätt fas-μ och rätt rating-set.

    Slutspel använder den lägre KO_MU_TOTAL och ratingset med lägre MSS-blend
    (mer vikt på färsk live-form); gruppspel använder default-μ och 0.30-blend."""
    stage = stage_for(m["home"], m["away"], m["kickoff"])
    if is_knockout_stage(stage):
        return MatchModel(m["home"], m["away"], ratings_ko, mu_total=KO_MU_TOTAL)
    return MatchModel(m["home"], m["away"], ratings_group, mu_total=MU_TOTAL)


def make_bet(date_str, m, category_key, category_name, selection, detail, odds,
             p_model, p_market, rationale, settle, player_market=False):
    p_used = shrink(p_model, p_market, odds) if not player_market else p_model
    edge = p_used * odds - 1.0
    label = value_label(edge, odds)
    rec = is_recommendable(settle[0], odds)
    if settle[0] in UNMODELED_MARKETS:
        label = "Undvik"            # omodellerad: bara marknadspris → ingen äkta edge
        edge = 0.0                  # nollställ artefakt-edgen (annars visas falsk +%)
    elif not rec and label in ("Spelvärt", "Chans"):
        label = "Neutralt"          # modellerad men longshot/högvarians → ej rek
    kel = kelly(p_used, odds) if rec else 0.0
    return {
        "id": "%s-%s-%s-%s" % (date_str, m["kambiId"], category_key, slugify(selection)),
        "matchId": m["kambiId"],
        "match": "%s – %s" % (m["home"], m["away"]),
        "homeFlag": FLAG_OF.get(m["home"], ""), "awayFlag": FLAG_OF.get(m["away"], ""),
        "kickoff": m["kickoff"],
        "categoryKey": category_key, "category": category_name,
        "selection": selection, "detail": detail,
        "odds": round(odds, 2),
        "modelProb": round(p_used, 4),
        "marketProb": round(p_market, 4) if p_market is not None else None,
        "edge": round(edge, 4),
        "value": label,
        "recommendable": rec,
        "kelly": round(kel, 5),
        "stakeWeight": 0.0,
        "confidence": confidence(edge, p_used, player_market),
        "rationale": rationale,
        "settleMarket": settle[0], "settlePick": settle[1],
        "settleLine": settle[2], "settlePlayer": settle[3],
    }


def bets_for_match(date_str, m, model, markets):
    """Alla kandidat-spel för en match, per kategori."""
    out = {k: [] for k, _n, _i in CATEGORIES}
    ph, pd, pa = model.p_1x2()
    lam_tot = model.lam_total()

    # --- Fulltid (1X2): bästa av de tre utfallen ---
    ft = markets.get("fulltid") or {}
    o1, ox, o2 = ft.get("1"), ft.get("X"), ft.get("2")
    mkt = devig([o1, ox, o2])
    if mkt:
        cands = []
        for sel, pm_, om_, pmk, name in (
                ("1", ph, o1, mkt[0], "%s vinner" % m["home"]),
                ("X", pd, ox, mkt[1], "Oavgjort"),
                ("2", pa, o2, mkt[2], "%s vinner" % m["away"])):
            rat = ("Modellen ger %s %.0f%% mot marknadens %.0f%% "
                   "(MSS %s–%s, målförväntan %.1f–%.1f)." % (
                       name.lower(), shrink(pm_, pmk) * 100, pmk * 100,
                       m.get("mssHome") or "–", m.get("mssAway") or "–",
                       model.lam_h, model.lam_a))
            cands.append(make_bet(date_str, m, "fulltid", "Fulltid",
                                  "%s (%s)" % (sel, name), name, om_,
                                  pm_, pmk, rat, ("1X2", sel, None, None)))
        out["fulltid"].append(max(cands, key=lambda b: b["edge"]))

    # --- Dubbelchans: ETT spel per match (bästa edge av 1X/12/X2) ---
    dc = markets.get("dubbelchans") or {}
    o1x, o12, ox2 = dc.get("1X"), dc.get("12"), dc.get("X2")
    mkt = devig([o1x, o12, ox2])
    if mkt:
        # OBS: 1X/12/X2 överlappar — varje grundutfall täcks av två av dem,
        # så de sanna sannolikheterna summerar till 2 (inte 1). Skala upp.
        mkt = [p * 2.0 for p in mkt]
        p1x, p12, px2 = model.p_double_chance()
        cands = []
        for sel, pm_, om_, pmk, name in (
                ("1X", p1x, o1x, mkt[0], "%s eller oavgjort" % m["home"]),
                ("12", p12, o12, mkt[1], "%s eller %s vinner" % (m["home"], m["away"])),
                ("X2", px2, ox2, mkt[2], "Oavgjort eller %s" % m["away"])):
            rat = ("Två utfall täcks: modellen ger %s %.0f%% mot marknadens "
                   "%.0f%%." % (name.lower(), shrink(pm_, pmk) * 100, pmk * 100))
            cands.append(make_bet(date_str, m, "dubbelchans", "Dubbelchans",
                                  "%s (%s)" % (sel, name), "Dubbelchans hela matchen",
                                  om_, pm_, pmk, rat, ("DC", sel, None, None)))
        out["dubbelchans"].append(max(cands, key=lambda b: b["edge"]))

    # --- Går vidare (ADVANCE): bara slutspel, driven av p_progress ---
    #     (90 min → förlängning → straffar). Marknaden "Lag som går vidare"
    #     finns bara för KO-matcher hos Kambi; dubbel KO-spärr via stage.
    adv = markets.get("advance") or {}
    oah, oaa = adv.get("home"), adv.get("away")
    if oah and oaa and is_knockout_stage(stage_for(m["home"], m["away"], m["kickoff"])):
        mkt = devig([oah, oaa])
        if mkt:
            p_h = model.p_progress()            # P(hemmalaget går vidare)
            cands = []
            for pm_, om_, pmk, pick, team in (
                    (p_h, oah, mkt[0], "home", m["home"]),
                    (1.0 - p_h, oaa, mkt[1], "away", m["away"])):
                rat = ("Avancemangsmodell (90 min → förlängning → straffar): %s "
                       "går vidare i %.0f%% mot marknadens %.0f%%." % (
                           team, shrink(pm_, pmk, om_) * 100, pmk * 100))
                cands.append(make_bet(
                    date_str, m, "avancemang", "Går vidare",
                    "%s går vidare" % team, "Vidare till nästa omgång (inkl. straffar)",
                    om_, pm_, pmk, rat, ("ADVANCE", pick, None, None)))
            out["avancemang"].append(max(cands, key=lambda b: b["edge"]))

    # --- Handikapp (asiatisk halvlinje): parvis avvigning, bästa sidan ---
    hk = markets.get("handikapp") or {}
    hk_line, ohk, oak = hk.get("line"), hk.get("home"), hk.get("away")
    if hk_line is not None and ohk and oak:
        mkt = devig([ohk, oak])
        p_cover = model.p_handicap(hk_line)
        cands = []
        for sel, pm_, om_, pmk, pick, ln in (
                ("%s %+.1f" % (m["home"], hk_line), p_cover, ohk, mkt[0], "home", hk_line),
                ("%s %+.1f" % (m["away"], -hk_line), 1.0 - p_cover, oak, mkt[1], "away", -hk_line)):
            rat = ("Med handikapp %+.1f täcker %s i %.0f%% av rutnätet "
                   "mot prisade %.0f%% (målförväntan %.1f–%.1f)." % (
                       ln, sel.split(" ")[0], shrink(pm_, pmk) * 100, pmk * 100,
                       model.lam_h, model.lam_a))
            cands.append(make_bet(date_str, m, "handikapp", "Handikapp",
                                  sel, "Asiatiskt handikapp, halvlinje", om_,
                                  pm_, pmk, rat, ("AH", pick, hk_line, None)))
        out["handikapp"].append(max(cands, key=lambda b: b["edge"]))

    # --- Antal mål (huvudlinje Ö/U) ---
    ou = markets.get("antal_mal") or {}
    line, oo, ou_ = ou.get("line"), ou.get("over"), ou.get("under")
    lam_mkt = None
    if line is not None and oo and ou_:
        mkt = devig([oo, ou_])
        p_over = model.p_over(line)
        lam_mkt = implied_lambda_total(mkt[0], line) if mkt else None
        # välj bara den sida som har bäst edge
        cands = []
        for sel, pm_, om_, pmk, pick in (("Över", p_over, oo, mkt[0], "over"),
                                         ("Under", 1.0 - p_over, ou_, mkt[1], "under")):
            rat = ("Modellens målförväntan %.2f mot marknadens %.2f → "
                   "%s %.1f ger %.0f%% mot prisade %.0f%%." % (
                       lam_tot, lam_mkt or 0.0, sel.lower(), line,
                       shrink(pm_, pmk) * 100, pmk * 100))
            cands.append(make_bet(date_str, m, "antal_mal", "Antal mål",
                                  "%s %.1f mål" % (sel, line),
                                  "Totalt antal mål i matchen", om_,
                                  pm_, pmk, rat, ("OU", pick, line, None)))
        out["antal_mal"].append(max(cands, key=lambda b: b["edge"]))

    # --- Lagmål (Antal mål för {lag}, huvudlinje): Poisson-svans mot λ ---
    lagmal = markets.get("lagmal") or {}
    for side, lam_team, team in (("home", model.lam_h, m["home"]),
                                 ("away", model.lam_a, m["away"])):
        row = lagmal.get(side) or {}
        tl, to_, tu = row.get("line"), row.get("over"), row.get("under")
        if tl is None or not to_ or not tu:
            continue
        mkt = devig([to_, tu])
        if not mkt:
            continue
        p_over_t = MatchModel.p_team_over(lam_team, tl)
        cands = []
        for sel, pm_, om_, pmk, pick in (
                ("över", p_over_t, to_, mkt[0], side + "_over"),
                ("under", 1.0 - p_over_t, tu, mkt[1], side + "_under")):
            rat = ("%s väntas göra %.2f mål: %s %.1f ger %.0f%% mot "
                   "prisade %.0f%%." % (team, lam_team, sel, tl,
                                        shrink(pm_, pmk) * 100, pmk * 100))
            cands.append(make_bet(date_str, m, "antal_mal", "Antal mål",
                                  "%s %s %.1f mål" % (team, sel, tl),
                                  "Antal mål för laget", om_, pm_, pmk, rat,
                                  ("TEAM_OU", pick, tl, None)))
        out["antal_mal"].append(max(cands, key=lambda b: b["edge"]))

    # --- Båda lagen gör mål ---
    btts = markets.get("btts") or {}
    oy, on = btts.get("yes"), btts.get("no")
    if oy and on:
        mkt = devig([oy, on])
        p_yes = model.p_btts()
        cands = []
        for sel, pm_, om_, pmk, pick in (("Ja", p_yes, oy, mkt[0], "yes"),
                                         ("Nej", 1.0 - p_yes, on, mkt[1], "no")):
            rat = ("Målförväntan %.1f–%.1f ger BTTS-%s %.0f%% mot prisade %.0f%%." % (
                model.lam_h, model.lam_a, sel.lower(),
                shrink(pm_, pmk) * 100, pmk * 100))
            cands.append(make_bet(date_str, m, "btts", "Båda lagen gör mål",
                                  "Båda lagen gör mål: %s" % sel,
                                  "Minst ett mål av vardera lag", om_,
                                  pm_, pmk, rat, ("BTTS", pick, None, None)))
        out["btts"].append(max(cands, key=lambda b: b["edge"]))

    # --- Korrekt resultat: HELA marknaden avvigas gemensamt, upp till 2 spel ---
    cs = markets.get("korrekt_resultat") or {}
    cs_rows = []
    for lab, odds in sorted(cs.items()):
        try:
            sh, sa = [int(x) for x in lab.split("-", 1)]
        except ValueError:
            continue
        if odds:
            cs_rows.append((lab, sh, sa, odds))
    mkt = devig([r[3] for r in cs_rows]) if cs_rows else None
    if mkt:
        cands = []
        for (lab, sh, sa, odds), pmk in zip(cs_rows, mkt):
            if odds > SCORE_MAX_ODDS:
                continue  # longshot-resultat: marginalbrus, ingen riktig edge
            pm_ = model.p_score(sh, sa)
            rat = ("Rutnätet ger %s %.1f%% mot marknadens %.1f%% "
                   "(hela resultatmarknaden avvigad gemensamt)." % (
                       lab, shrink(pm_, pmk, odds) * 100, pmk * 100))
            cands.append(make_bet(date_str, m, "korrekt_resultat", "Korrekt resultat",
                                  "Resultat %s" % lab, "Slutresultat efter full tid",
                                  odds, pm_, pmk, rat, ("CS", lab, None, None)))
        cands.sort(key=lambda b: -b["edge"])
        out["korrekt_resultat"].extend(cands[:2])

    # --- Halvlek: Halvtid-1X2 + Antal mål 1:a halvlek — de 2 bästa.
    #     Rättas manuellt i appen (auto-rättningen gäller bara fulltid). ---
    hl_cands = []
    ht = markets.get("halvtid_1x2") or {}
    h1, hx, h2 = ht.get("1"), ht.get("X"), ht.get("2")
    mkt = devig([h1, hx, h2])
    if mkt:
        p1h, pxh, p2h = model.p_1x2_first_half()
        trio = []
        for sel, pm_, om_, pmk, name in (
                ("1", p1h, h1, mkt[0], "%s leder i halvtid" % m["home"]),
                ("X", pxh, hx, mkt[1], "Oavgjort i halvtid"),
                ("2", p2h, h2, mkt[2], "%s leder i halvtid" % m["away"])):
            rat = ("Första halvlek väntas ge %.2f mål (44%% av matchens %.2f): "
                   "%s %.0f%% mot prisade %.0f%%. Rättas manuellt." % (
                       model.lam_total() * 0.44, model.lam_total(),
                       name.lower(), shrink(pm_, pmk) * 100, pmk * 100))
            trio.append(make_bet(date_str, m, "halvlek", "Halvlek",
                                 "Halvtid: %s (%s)" % (sel, name),
                                 "Resultat efter första halvlek", om_,
                                 pm_, pmk, rat, ("1H_1X2", sel, None, None)))
        hl_cands.append(max(trio, key=lambda b: b["edge"]))

    ou1 = markets.get("antal_mal_1h") or {}
    l1, oo1, uu1 = ou1.get("line"), ou1.get("over"), ou1.get("under")
    if l1 is not None and oo1 and uu1:
        mkt = devig([oo1, uu1])
        p_over1 = model.p_over_first_half(l1)
        pair = []
        for sel, pm_, om_, pmk, pick in (("Över", p_over1, oo1, mkt[0], "over"),
                                         ("Under", 1.0 - p_over1, uu1, mkt[1], "under")):
            rat = ("Halvleksrutnätet (λ×0.44) ger %s %.1f i första halvlek "
                   "%.0f%% mot prisade %.0f%%. Rättas manuellt." % (
                       sel.lower(), l1, shrink(pm_, pmk) * 100, pmk * 100))
            pair.append(make_bet(date_str, m, "halvlek", "Halvlek",
                                 "%s %.1f mål i 1:a halvlek" % (sel, l1),
                                 "Antal mål i första halvlek", om_,
                                 pm_, pmk, rat, ("1H_OU", pick, l1, None)))
        hl_cands.append(max(pair, key=lambda b: b["edge"]))
    hl_cands.sort(key=lambda b: -b["edge"])
    out["halvlek"].extend(hl_cands[:2])

    # --- Halvtid/Fulltid: 9-vägsmarknaden avvigas gemensamt, bästa utfallet ---
    htft = markets.get("halvtid_fulltid") or {}
    keys = [k for k in HTFT_KEYS if htft.get(k)]
    mkt = devig([htft[k] for k in keys]) if len(keys) >= 2 else None
    if mkt:
        p_map = model.p_htft()
        cands = []
        for k, pmk in zip(keys, mkt):
            odds = htft[k]
            if odds > SCORE_MAX_ODDS:
                continue
            pm_ = p_map.get(k, 0.0)
            rat = ("Halvleksrutnäten (44/56-delning av λ) ger %s %.1f%% mot "
                   "marknadens %.1f%%." % (k, shrink(pm_, pmk, odds) * 100, pmk * 100))
            cands.append(make_bet(date_str, m, "halvtid_fulltid", "Halvtid/Fulltid",
                                  "Halvtid/Fulltid %s" % k,
                                  "Resultat vid halvtid / vid fulltid",
                                  odds, pm_, pmk, rat, ("HTFT", k, None, None)))
        if cands:
            out["halvtid_fulltid"].append(max(cands, key=lambda b: b["edge"]))

    # --- Spelarmarknader: tilt = modellens målförväntan vs marknadens ---
    ratio = 1.0
    if lam_mkt and lam_mkt > 0.3:
        ratio = lam_tot / lam_mkt
    tilt_scorer = max(0.80, min(1.25, ratio))
    tilt_two = max(0.70, min(1.45, ratio * ratio))
    tilt_shots = max(0.90, min(1.15, ratio ** 0.5))
    tilt_txt = ("Modellen väntar %.2f mål mot marknadens %.2f"
                % (lam_tot, lam_mkt)) if lam_mkt else "Marknadsanchored (ingen Ö/U-linje)"

    for row in markets.get("malgorare") or []:
        if row["odds"] > PLAYER_MAX_ODDS:
            continue
        p_fair = (1.0 / row["odds"]) / player_margin(MARGIN_SCORER, row["odds"])
        p_adj = min(0.92, p_fair * tilt_scorer)
        rat = "%s. Avvigat pris %.0f%% → justerat %.0f%%." % (
            tilt_txt, p_fair * 100, p_adj * 100)
        out["malgorare"].append(make_bet(
            date_str, m, "malgorare", "Målgörare",
            "%s gör mål" % row["player"], "Målgörare när som helst i matchen",
            row["odds"], p_adj, None, rat,
            ("PLAYER", "scorer", None, row["player"]), player_market=True))

    for row in markets.get("tvaplus") or []:
        if row["odds"] > PLAYER_MAX_ODDS:
            continue
        p_fair = (1.0 / row["odds"]) / player_margin(MARGIN_TWOPLUS, row["odds"])
        p_adj = min(0.85, p_fair * tilt_two)
        rat = "%s. 2+ mål skalar kvadratiskt: %.1f%% → %.1f%%." % (
            tilt_txt, p_fair * 100, p_adj * 100)
        out["spelarspecial"].append(make_bet(
            date_str, m, "spelarspecial", "Spelarspecial",
            "%s gör 2+ mål" % row["player"], "Minst två mål av spelaren",
            row["odds"], p_adj, None, rat,
            ("PLAYER", "twoplus", None, row["player"]), player_market=True))

    for row in markets.get("skott") or []:
        if row["odds"] > PLAYER_MAX_ODDS:
            continue
        p_fair = (1.0 / row["odds"]) / player_margin(MARGIN_SHOTS, row["odds"])
        p_adj = min(0.95, p_fair * tilt_shots)
        rat = "%s. Skott på mål följer målförväntan svagt (√-tilt)." % tilt_txt
        out["spelarspecial"].append(make_bet(
            date_str, m, "spelarspecial", "Spelarspecial",
            "%s över %.1f skott på mål" % (row["player"], row["line"]),
            "Opta-avgjord spelarmarknad", row["odds"], p_adj, None, rat,
            ("PLAYER", "shots", row["line"], row["player"]), player_market=True))

    # --- Hörnor: ingen hörnmodell finns — ärlig marknadsankring som
    #     spelarmarknaderna. Implicit hörn-λ löses ur den avvigade
    #     Över-sannolikheten (Poisson-inversion) och tiltas med
    #     √(λ_modell/λ_marknad) för MÅLEN, hårt clampat [0.92, 1.10]:
    #     anfallstryck korrelerar bara svagt med hörnor. ---
    hor = markets.get("hornor") or {}
    cl, co, cu = hor.get("line"), hor.get("over"), hor.get("under")
    if cl is not None and co and cu:
        mkt = devig([co, cu])
        lam_corner = implied_lambda_poisson(mkt[0], cl) if mkt else None
        if lam_corner:
            tilt = 1.0
            if lam_mkt and lam_mkt > 0.3:
                tilt = max(0.92, min(1.10, (lam_tot / lam_mkt) ** 0.5))
            p_over_c = MatchModel.p_team_over(lam_corner * tilt, cl)
            cands = []
            for sel, pm_, om_, pmk, pick in (("Över", p_over_c, co, mkt[0], "over"),
                                             ("Under", 1.0 - p_over_c, cu, mkt[1], "under")):
                rat = ("Hörnor är marknadsprissatta (ingen hörnmodell) med mjuk "
                       "modelltilt ×%.2f från målförväntan: %s %.1f hörnor "
                       "%.0f%% mot prisade %.0f%%. Rättas manuellt." % (
                           tilt, sel.lower(), cl, pm_ * 100, pmk * 100))
                cands.append(make_bet(date_str, m, "hornor", "Hörnor",
                                      "%s %.1f hörnor" % (sel, cl),
                                      "Totalt antal hörnor i matchen", om_,
                                      pm_, pmk, rat, ("CORNERS", pick, cl, None),
                                      player_market=True))
            out["hornor"].append(max(cands, key=lambda b: b["edge"]))

    # --- Kort: ren avvigning (tilt 1.0) — bara för överblick, ingen modell ---
    krt = markets.get("kort") or {}
    kl, ko_, ku = krt.get("line"), krt.get("over"), krt.get("under")
    if kl is not None and ko_ and ku:
        mkt = devig([ko_, ku])
        if mkt:
            rat = ("Marknadsprissatt — modellen har ingen kortmodell; "
                   "visas för överblick. Rättas manuellt.")
            for sel, om_, pmk, pick in (("Över", ko_, mkt[0], "over"),
                                        ("Under", ku, mkt[1], "under")):
                out["kort"].append(make_bet(date_str, m, "kort", "Kort",
                                            "%s %.1f kort" % (sel, kl),
                                            "Totalt antal kort i matchen", om_,
                                            pmk, pmk, rat, ("CARDS", pick, kl, None),
                                            player_market=True))

    return out


def match_info(m, model, mss_map):
    ph, pd, pa = model.p_1x2()
    stage = stage_for(m["home"], m["away"], m["kickoff"])
    info = {
        "id": m["kambiId"], "kickoff": m["kickoff"],
        "stage": stage,
        "home": m["home"], "away": m["away"],
        "homeFlag": FLAG_OF.get(m["home"], ""), "awayFlag": FLAG_OF.get(m["away"], ""),
        "channel": tv_channels.channel_for(m["home"], m["away"]),
        "pHome": round(ph, 3), "pDraw": round(pd, 3), "pAway": round(pa, 3),
        "oddsHome": m.get("odds1"), "oddsDraw": m.get("oddsX"), "oddsAway": m.get("odds2"),
        "lambdaHome": round(model.lam_h, 2), "lambdaAway": round(model.lam_a, 2),
        "mssHome": mss_map.get(m["home"]), "mssAway": mss_map.get(m["away"]),
    }
    # Slutspel: additiva fält (gamla klienter ignorerar dem). pAdvance = "vem går
    # vidare" via 90 min → förlängning → straffar; 90-min-1X2 ovan är oförändrat.
    if is_knockout_stage(stage):
        p_adv = model.p_progress()
        info["knockout"] = True
        info["pAdvanceHome"] = round(p_adv, 3)
        info["pAdvanceAway"] = round(1.0 - p_adv, 3)
    return info


def attach_scorer_analysis(match_infos, by_team, totals):
    """Lägg additiv 'scorerAnalysis' (topp-N anytime-skyttar, REN analys) på
    slutspelsmatcher. Använder matchkortets λ och facitens målgörartabell.
    Gör inget för gruppmatcher eller när lagen saknar måldata."""
    for info in match_infos:
        if not info.get("knockout"):
            continue
        rows = scorer_model.match_scorer_analysis(
            info["home"], info["away"], info["lambdaHome"], info["lambdaAway"],
            by_team, totals)
        if rows:
            info["scorerAnalysis"] = rows


def load_fixtures():
    """Fixture-liggaren: {kambiId: {home, away, kickoff, stage}} — ackumulerar
    alla matcher feeden någonsin listat. Saknad/trasig fil → tom dict."""
    if os.path.exists(FIXTURES_PATH):
        try:
            with open(FIXTURES_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _iso_date(s):
    try:
        return datetime.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def normalize_results_orientation(results, fixtures, matches):
    """Vänder ett resultats home/away (och ställning, halvtid, winner) så att det
    matchar fixturens/Kambis lagordning. Resultatkällorna (football-data och
    facit-reserven) kan lista lagen i omvänd ordning mot Kambi; utan detta hittar
    varken historiken (`past`) eller appens matchStatus/auto-rättning matchen — de
    jämför home==home && away==away — och slutställningen skulle visas spegelvänd.

    Orienteringen avgörs PER MATCHINSTANS, inte per oordnat lagpar: samma lagpar
    kan mötas två gånger i ett VM (gruppspel A–B, sedan slutspel B–A) och Kambi
    kan då sätta hemma/borta olika. Vi samlar alla kandidat-orienteringar för
    paret (med datum) och väljer den vars avspark ligger närmast resultatets
    datum. Saknar resultatet datum (facit-reserven) används parets orientering
    bara om ALLA kandidater är eniga — annars lämnas resultatet orört (hellre
    oförändrat än spegelvänt). Idempotent: redan rättvända resultat rörs inte."""
    cands = {}  # frozenset({home, away}) -> [(date_prefix, home, away), ...]

    def add(home, away, kickoff):
        if home and away:
            cands.setdefault(frozenset((home, away)), []).append(
                ((kickoff or "")[:10], home, away))

    for m in matches:
        add(m.get("home"), m.get("away"), m.get("kickoff"))
    for fx in fixtures.values():
        add(fx.get("home"), fx.get("away"), fx.get("kickoff"))

    def canon_for(home, away, rdate):
        opts = cands.get(frozenset((home, away)))
        if not opts:
            return None
        rd = _iso_date(rdate)
        dated = [o for o in opts if _iso_date(o[0])]
        if rd and dated:
            best = min(dated, key=lambda o: abs((_iso_date(o[0]) - rd).days))
            return (best[1], best[2])
        # Utan datum: bara entydig orientering används; tvetydigt -> rör inte.
        orients = {(o[1], o[2]) for o in opts}
        return next(iter(orients)) if len(orients) == 1 else None

    for r in results:
        canon = canon_for(r.get("home"), r.get("away"), r.get("date"))
        if canon and canon == (r.get("away"), r.get("home")):
            r["home"], r["away"] = r["away"], r["home"]
            r["scoreHome"], r["scoreAway"] = r.get("scoreAway"), r.get("scoreHome")
            if r.get("htHome") is not None and r.get("htAway") is not None:
                r["htHome"], r["htAway"] = r.get("htAway"), r.get("htHome")
            if r.get("winner") == "home":
                r["winner"] = "away"
            elif r.get("winner") == "away":
                r["winner"] = "home"
    return results


def build_past(fixtures, results, ratings, ratings_ko, mss_map, today_local, now, exclude=None):
    """Spelade (och dagens pågående) matcher t.o.m. idag, grupperade per dag,
    äldst först. Samma kortform som match_info så appen renderar identiska
    matchkort; odds = null (Kambi har släppt avsparkade matcher) och slut-
    ställningen kommer ur feedens `results` via appens matchStatus. Modellens
    1X2 räknas om ur lagstyrkorna för överblick.

    Inklusion: matcher med resultat (historik, visas som FT) PLUS dagens redan
    AVSPARKADE matcher utan resultat än (pågår just nu / resultat på väg) — Kambi
    tar bort dem ur `day` när de börjar, så utan detta blir live-matchen osynlig
    under hela speltiden. `exclude` (frozenset {home, away}) hoppar över dagens
    ännu ospelade matcher som redan ligger i `day`. Appen slår ihop date==idag i
    Idag-sektionen."""
    exclude = exclude or set()

    def has_result(home, away, ko):
        d = (ko or "")[:10]
        for r in results:
            if r.get("home") != home or r.get("away") != away:
                continue
            rd = (r.get("date") or "")[:10]
            if not rd or not d:
                return True
            try:
                if abs((datetime.date.fromisoformat(rd)
                        - datetime.date.fromisoformat(d)).days) <= 2:
                    return True
            except ValueError:
                return True
        return False

    by_day = {}
    for kid, fx in fixtures.items():
        ko = fx.get("kickoff")
        kdt = parse_kickoff(ko)
        md = stockholm_matchday(kdt) if kdt else None
        if md is None or md > today_local:
            continue
        if frozenset((fx.get("home"), fx.get("away"))) in exclude:
            continue
        if not has_result(fx.get("home"), fx.get("away"), ko):
            # Inget resultat än: ta bara med dagens redan avsparkade matcher
            # (pågår nu / resultat på väg). Äldre matcher utan resultat (uppskjutna
            # / dataglapp) hoppas över så de inte visas som spökkort i historiken.
            if not (md == today_local and kdt and kdt < now):
                continue
        m = {"kambiId": kid, "kickoff": ko, "home": fx["home"], "away": fx["away"]}
        model = build_match_model(m, ratings, ratings_ko)
        by_day.setdefault(md, []).append(match_info(m, model, mss_map))
    out = []
    for d in sorted(by_day):
        rows = sorted(by_day[d], key=lambda r: r.get("kickoff") or "")
        out.append({"date": d.isoformat(), "matches": rows})
    return out


def allocate_weights(bets):
    """Normalisera kvarts-Kelly till stakeWeight över de rekommenderade spelen."""
    rec = [b for b in bets if b["value"] in ("Spelvärt", "Chans") and b["kelly"] > 0]
    total = sum(b["kelly"] for b in rec)
    if total <= 0:
        return
    for b in rec:
        b["stakeWeight"] = round(b["kelly"] / total, 4)


def update_clv_log(pool, now):
    """Framåtriktad CLV-mätning (closing line value). Loggar varje visat spels
    rekommendationsodds och följer stängningsoddset (sista odds före avspark).
    Slår vi stängningslinjen (recOdds > closeOdds) är det det mest sample-
    effektiva beviset på äkta edge — utan att invänta resultat. Lagrar även
    value/recommendable + settle-fält så skugg-P&L kan räknas på det vi numera
    INTE rekommenderar (validerar exkluderingarna). En rad per unikt spel-id."""
    try:
        log = json.load(open(CLV_PATH)) if os.path.exists(CLV_PATH) else {}
    except Exception:
        log = {}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for b in pool:
        ko = parse_kickoff(b.get("kickoff"))
        e = log.get(b["id"])
        if e is None:
            log[b["id"]] = {
                "match": b["match"], "market": b["settleMarket"],
                "selection": b["selection"], "settlePick": b["settlePick"],
                "settleLine": b.get("settleLine"), "settlePlayer": b.get("settlePlayer"),
                "kickoff": b.get("kickoff"), "value": b["value"],
                "recommendable": b.get("recommendable", False),
                "recOdds": b["odds"], "recTime": stamp,
                "closeOdds": b["odds"], "closeTime": stamp,
            }
        elif ko is None or ko > now:          # uppdatera stängning tills avspark
            e["closeOdds"] = b["odds"]; e["closeTime"] = stamp
            e["value"] = b["value"]; e["recommendable"] = b.get("recommendable", False)
    with open(CLV_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1, sort_keys=True)


def build_push(date_local, top_bets, day_matches, next_day, played_today=False):
    play = [b for b in top_bets if b["value"] in ("Spelvärt", "Chans")]
    months = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
              "augusti", "september", "oktober", "november", "december"]
    nice = "%d %s" % (date_local.day, months[date_local.month - 1])
    if not day_matches:
        if played_today:
            title = "Dagens matcher spelade %s" % nice
            body = "Alla dagens matcher har spelats. Resultaten finns i appen."
        else:
            title = "VM-vilodag %s" % nice
            body = "Inga matcher idag."
        if next_day:
            body += " Nästa matchdag: %s." % next_day
        return {"title": title, "body": body}
    title = "VM-rapport %s — %d spelvärda spel" % (nice, len(play))
    if play:
        rows = ["%s %s: %s @%.2f (%+.0f%%)" % (b["homeFlag"], b["match"], b["selection"],
                                               b["odds"], b["edge"] * 100) for b in play[:3]]
        body = " · ".join(rows)
        body += " — öppna appen för hela dagsrapporten och budgetfördelningen."
    else:
        body = ("%d matcher idag men inga tydliga värdespel — modellen och "
                "Svenska Spel är överens. Dagsrapporten ligger i appen.") % len(day_matches)
    return {"title": title, "body": body}


def build_headline(date_local, day_matches, top_bets, played_today=False):
    if not day_matches:
        # Tom day.matches betyder bara att inga KOMMANDE matcher finns kvar idag.
        # Hade dagen matcher som redan sparkat igång (played_today) är det ingen
        # vilodag — undvik den missvisande rubriken (annars står "Vilodag" i det
        # nattfönster då alla dagens matcher börjat men dygnet ännu inte rullat).
        if played_today:
            return ("Dagens matcher är spelade",
                    "Alla dagens matcher har spelats — resultat och historik finns i appen.")
        return "Vilodag — inga VM-matcher idag", "Vila benen. Statistiken och historiken finns i appen."
    names = ["%s–%s" % (mi["home"], mi["away"]) for mi in day_matches]
    play = [b for b in top_bets if b["value"] in ("Spelvärt", "Chans")]
    if date_local.isoformat() == "2026-06-11":
        head = "VM-premiär! %s öppnar turneringen" % names[0]
    else:
        head = "Matchdag: %s" % (", ".join(names[:3]) + (" …" if len(names) > 3 else ""))
    summary = "%d matcher, %d spel med värde enligt modellen." % (len(day_matches), len(play))
    if play:
        b = play[0]
        summary += " Bäst: %s @%.2f (%+.1f%% edge)." % (b["selection"], b["odds"], b["edge"] * 100)
    return head, summary


def main():
    print("Stakbrons VM-feed — generering startar", now_utc_iso())
    ratings, mss_map, elo_source = build_ratings()
    # Slutspels-ratingset: lägre MSS-blend (mer vikt på färsk live-form, den
    # frusna 11-juni-priorn är nu äldre). Källhämtningen cachas i wc_model så
    # detta inte gör ett extra nätanrop.
    ratings_ko, _, _ = build_ratings(blend=KO_MSS_BLEND)
    print("  lagstyrkor: %d lag, Elo-källa=%s (grupp-blend %.2f / KO-blend %.2f)"
          % (len(ratings), elo_source, MSS_BLEND, KO_MSS_BLEND))

    matches = kambi_wc.fetch_match_list()
    print("  Kambi: %d kommande matcher" % len(matches))

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_local = stockholm_matchday(now_utc)
    date_str = today_local.isoformat()

    by_day = {}
    for m in matches:
        ko = parse_kickoff(m["kickoff"])
        if ko is None:
            continue
        by_day.setdefault(stockholm_matchday(ko), []).append(m)

    todays = sorted(by_day.get(today_local, []), key=lambda m: m["kickoff"])
    future_days = sorted(d for d in by_day if d > today_local)
    next_day = future_days[0].isoformat() if future_days else None

    # --- Dagens matcher: detaljmarknader + spel ---
    day_matches, all_bets = [], []
    for m in todays:
        m["mssHome"] = mss_map.get(m["home"])
        m["mssAway"] = mss_map.get(m["away"])
        model = build_match_model(m, ratings, ratings_ko)
        day_matches.append(match_info(m, model, mss_map))
        try:
            mk = kambi_wc.fetch_match_markets(m["kambiId"], m["home"], m["away"])
        except Exception as e:
            print("  ! detaljmarknader failade för %s: %s" % (m["kambiId"], e), file=sys.stderr)
            mk = {"fulltid": {"1": m.get("odds1"), "X": m.get("oddsX"), "2": m.get("odds2")},
                  "antal_mal": {"line": m.get("ouLine"), "over": m.get("oddsOver"),
                                "under": m.get("oddsUnder")},
                  "btts": {}, "malgorare": [], "tvaplus": [], "skott": [],
                  "advance": {}}
        per_cat = bets_for_match(date_str, m, model, mk)
        for k, lst in per_cat.items():
            all_bets.extend(lst)

    # --- Topp 10 "Dagens mest spelvärda" — BARA rekommenderbara marknader
    #     (modellens styrkor), max 3 per match. Omodellerade/longshot-spel hamnar
    #     aldrig i rubriklistan. ---
    rec_pool = [b for b in all_bets if b.get("recommendable")]
    top_bets, per_match = [], {}
    for b in sorted(rec_pool, key=lambda b: -b["edge"]):
        if per_match.get(b["matchId"], 0) >= MAX_PER_MATCH_TOP:
            continue
        top_bets.append(b)
        per_match[b["matchId"]] = per_match.get(b["matchId"], 0) + 1
        if len(top_bets) >= MAX_TOP_BETS:
            break
    # Topp 10-garanti: dagar med få matcher fyller cap-passet inte listan —
    # fyll på med resterande rekommenderbara spel på edge, utan per-match-tak.
    if len(top_bets) < MAX_TOP_BETS:
        chosen = set(map(id, top_bets))
        for b in sorted(rec_pool, key=lambda b: -b["edge"]):
            if id(b) in chosen:
                continue
            top_bets.append(b)
            chosen.add(id(b))
            if len(top_bets) >= MAX_TOP_BETS:
                break
    allocate_weights(top_bets)

    # --- Topp 5 per kategori (max 2 per match inom kategorin) ---
    categories = []
    for key, name, icon in CATEGORIES:
        cat_bets, seen = [], {}
        for b in sorted((x for x in all_bets if x["categoryKey"] == key),
                        key=lambda b: -b["edge"]):
            if seen.get(b["matchId"], 0) >= 2:
                continue
            cat_bets.append(b)
            seen[b["matchId"]] = seen.get(b["matchId"], 0) + 1
            if len(cat_bets) >= MAX_PER_CATEGORY:
                break
        categories.append({"key": key, "name": name, "icon": icon, "bets": cat_bets})

    # CLV-logg: följ rekommendations- vs stängningsodds för alla visade spel
    # (topp 10 + kategorier, deduplicerat) — framåtriktad edge-validering.
    clv_pool, clv_seen = [], set()
    for b in top_bets + [x for c in categories for x in c["bets"]]:
        if b["id"] not in clv_seen:
            clv_seen.add(b["id"]); clv_pool.append(b)
    try:
        update_clv_log(clv_pool, now_utc)
    except Exception as e:
        print("  ! CLV-logg failade: %s" % e, file=sys.stderr)

    # --- Kommande dagar (modellens 1X2 ur listView-odds, inga detaljspel) ---
    upcoming = []
    for d in future_days[:4]:
        rows = []
        for m in sorted(by_day[d], key=lambda m: m["kickoff"]):
            model = build_match_model(m, ratings, ratings_ko)
            rows.append(match_info(m, model, mss_map))
        upcoming.append({"date": d.isoformat(), "matches": rows})

    # Resultat + avancemang: progress är alltid en komplett dict (tomma
    # listor innan slutspelet) så appen kan avkoda den ovillkorligt.
    results, progress = results_wc.fetch_results()

    # Målgörartabell ur facit (alla matchers scorers) → ren skytteanalys per
    # slutspelsmatch. Additivt 'scorerAnalysis'-fält, rekommenderas aldrig.
    scorer_by_team, scorer_totals = scorer_model.team_goal_table(results)
    attach_scorer_analysis(day_matches, scorer_by_team, scorer_totals)
    for u in upcoming:
        attach_scorer_analysis(u["matches"], scorer_by_team, scorer_totals)

    # Resultaten orienteras till Kambis lagordning (källorna kan lista lagen
    # omvänt) så historik, matchStatus och auto-rättning hittar matchen och
    # visar ställningen rättvänd.
    fixtures = load_fixtures()
    results = normalize_results_orientation(results, fixtures, matches)

    # Historik: spelade matcher (t.o.m. idag med resultat) ur fixture-liggaren,
    # så Matcher-vyn kan visa hela turneringen bakåt markerad som FT. Dagens
    # ännu ospelade matcher (redan i `day`) exkluderas för att undvika dubblett.
    day_keys = {frozenset((mi["home"], mi["away"])) for mi in day_matches}
    past = build_past(fixtures, results, ratings, ratings_ko, mss_map, today_local,
                      now_utc, exclude=day_keys)

    # --- Turneringssektionen (scripts/tournament.py — Monte Carlo-simulering,
    #     ägs av separat modul). Failsafe: feeden ska genereras även om
    #     tournament.py saknas eller simuleringen failar. ---
    tour = None
    try:
        import tournament
        tour = tournament.build_tournament_section(ratings, ratings_ko, mss_map,
                                                   date_str, progress=progress,
                                                   match_list=matches, results=results)
    except Exception as e:
        print("  ! turneringssektionen failade: %s" % e, file=sys.stderr)
        tour = None

    # --- VM-tipset-kupongen (scripts/vmtipset.py — Svenska Spels öppna
    #     omgång, ägs av separat modul). Failsafe som tournament: feeden ska
    #     genereras även om vmtipset.py saknas eller kupongen failar; fältet
    #     är None när ingen omgång är öppen (optional i appen). ---
    vmt = None
    try:
        import vmtipset
        vmt = vmtipset.build_vmtipset_section(ratings, date_str)
    except Exception as e:
        print("  ! vmtipset-sektionen failade: %s" % e, file=sys.stderr)
        vmt = None

    # Hade dagens matchdag matcher som redan sparkat igång? (då är tom day.matches
    # ingen vilodag, bara "alla dagens matcher spelade").
    played_today = any(d.get("date") == date_str for d in past)
    headline, summary = build_headline(today_local, day_matches, top_bets, played_today)
    push = build_push(today_local, top_bets, day_matches, next_day, played_today)

    feed = {
        "schemaVersion": 1,
        "generatedAt": now_utc_iso(),
        "model": {
            "name": "Oscars funderingar (MSS + live-Elo)",
            "version": MODEL_VERSION,
            "eloSource": elo_source,
            "muTotal": MU_TOTAL,
            "muGroup": MU_TOTAL,
            "muKnockout": KO_MU_TOTAL,
            "eloPerGoal": ELO_PER_GOAL,
            "mssBlend": MSS_BLEND,
            "mssBlendKnockout": KO_MSS_BLEND,
            "shrink": SHRINK_MODEL,
        },
        "day": {
            "date": date_str,
            "headline": headline,
            "summary": summary,
            "matchCount": len(day_matches),
            "matches": day_matches,
            "topBets": top_bets,
            "categories": categories,
        },
        "upcoming": upcoming,
        "past": past,
        "tournament": tour,
        "vmtipset": vmt,
        "results": results,
        "progress": progress,
        "push": push,
    }

    os.makedirs(os.path.dirname(FEED_PATH), exist_ok=True)
    os.makedirs(DAYS_DIR, exist_ok=True)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=1)
    # Dagsarkivet ska bevara dagens FULLA spelslate (morgonkörningen). Tidigare
    # skrevs det över vid varje körning → nattens tomma day.matches (alla matcher
    # avsparkade) raderade dagens rekommendationer och gjorde arkivet oanvändbart
    # för historik/backtest. Skriv bara om den nya versionen har minst lika många
    # matcher som den arkiverade.
    day_path = os.path.join(DAYS_DIR, "%s.json" % date_str)
    prev_count = -1
    if os.path.exists(day_path):
        try:
            with open(day_path, encoding="utf-8") as f:
                prev_count = len(json.load(f).get("day", {}).get("matches", []))
        except Exception:
            prev_count = -1
    if len(day_matches) >= prev_count:
        with open(day_path, "w", encoding="utf-8") as f:
            json.dump(feed, f, ensure_ascii=False, indent=1)
    else:
        print("  arkiv %s behålls (%d matcher) — denna körning har %d"
              % (date_str, prev_count, len(day_matches)))

    # Fixture-liggare: uppdatera den redan inlästa liggaren med dagens/kommande
    # matcher (för historik/analys) och spara.
    for m in matches:
        fixtures[m["kambiId"]] = {
            "home": m["home"], "away": m["away"], "kickoff": m["kickoff"],
            "stage": stage_for(m["home"], m["away"], m["kickoff"]),
        }
    with open(FIXTURES_PATH, "w", encoding="utf-8") as f:
        json.dump(fixtures, f, ensure_ascii=False, indent=1, sort_keys=True)

    n_play = len([b for b in top_bets if b["value"] in ("Spelvärt", "Chans")])
    print("Klart: %d matcher idag, %d spel totalt, %d rekommenderade, %d resultat."
          % (len(day_matches), len(all_bets), n_play, len(results)))
    print("  headline: %s" % headline)
    print("  push: %s — %s" % (push["title"], push["body"][:120]))


if __name__ == "__main__":
    main()
