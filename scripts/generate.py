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
  6. Topp 10 över alla kategorier + topp 5 per Svenska Spel-kategori.
  7. Resultat för spelade matcher (results_wc.py) → appens auto-rättning.

Körs utan pip-paket (bara standardbiblioteket), Python 3.9+.
"""
import json
import os
import sys
import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wc_data import FLAG_OF, GROUP_OF, stage_for
from wc_model import (MatchModel, build_ratings, devig, shrink,
                      implied_lambda_total, MU_TOTAL, MSS_BLEND, SHRINK_MODEL)
import kambi_wc
import results_wc

STOCKHOLM = ZoneInfo("Europe/Stockholm")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
DAYS_DIR = os.path.join(ROOT, "data", "days")
FIXTURES_PATH = os.path.join(ROOT, "data", "fixtures.json")

MODEL_VERSION = "1.0.0"

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


def player_margin(base, odds):
    return base * (1.0 + 0.004 * odds)

CATEGORIES = [
    ("fulltid", "Fulltid", "⚽"),
    ("antal_mal", "Antal mål", "🥅"),
    ("btts", "Båda lagen gör mål", "🤝"),
    ("malgorare", "Målgörare", "🎯"),
    ("spelarspecial", "Spelarspecial", "👟"),
]


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


def make_bet(date_str, m, category_key, category_name, selection, detail, odds,
             p_model, p_market, rationale, settle, player_market=False):
    p_used = shrink(p_model, p_market, odds) if not player_market else p_model
    edge = p_used * odds - 1.0
    label = value_label(edge, odds)
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
        "kelly": round(kelly(p_used, odds), 5),
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

    return out


def match_info(m, model, mss_map):
    ph, pd, pa = model.p_1x2()
    return {
        "id": m["kambiId"], "kickoff": m["kickoff"],
        "stage": stage_for(m["home"], m["away"], m["kickoff"]),
        "home": m["home"], "away": m["away"],
        "homeFlag": FLAG_OF.get(m["home"], ""), "awayFlag": FLAG_OF.get(m["away"], ""),
        "pHome": round(ph, 3), "pDraw": round(pd, 3), "pAway": round(pa, 3),
        "oddsHome": m.get("odds1"), "oddsDraw": m.get("oddsX"), "oddsAway": m.get("odds2"),
        "lambdaHome": round(model.lam_h, 2), "lambdaAway": round(model.lam_a, 2),
        "mssHome": mss_map.get(m["home"]), "mssAway": mss_map.get(m["away"]),
    }


def allocate_weights(bets):
    """Normalisera kvarts-Kelly till stakeWeight över de rekommenderade spelen."""
    rec = [b for b in bets if b["value"] in ("Spelvärt", "Chans") and b["kelly"] > 0]
    total = sum(b["kelly"] for b in rec)
    if total <= 0:
        return
    for b in rec:
        b["stakeWeight"] = round(b["kelly"] / total, 4)


def build_push(date_local, top_bets, day_matches, next_day):
    play = [b for b in top_bets if b["value"] in ("Spelvärt", "Chans")]
    months = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
              "augusti", "september", "oktober", "november", "december"]
    nice = "%d %s" % (date_local.day, months[date_local.month - 1])
    if not day_matches:
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


def build_headline(date_local, day_matches, top_bets):
    if not day_matches:
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
    print("  lagstyrkor: %d lag, Elo-källa=%s" % (len(ratings), elo_source))

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
        model = MatchModel(m["home"], m["away"], ratings)
        day_matches.append(match_info(m, model, mss_map))
        try:
            mk = kambi_wc.fetch_match_markets(m["kambiId"])
        except Exception as e:
            print("  ! detaljmarknader failade för %s: %s" % (m["kambiId"], e), file=sys.stderr)
            mk = {"fulltid": {"1": m.get("odds1"), "X": m.get("oddsX"), "2": m.get("odds2")},
                  "antal_mal": {"line": m.get("ouLine"), "over": m.get("oddsOver"),
                                "under": m.get("oddsUnder")},
                  "btts": {}, "malgorare": [], "tvaplus": [], "skott": []}
        per_cat = bets_for_match(date_str, m, model, mk)
        for k, lst in per_cat.items():
            all_bets.extend(lst)

    # --- Topp 10 över alla kategorier (max 3 per match) ---
    top_bets, per_match = [], {}
    for b in sorted(all_bets, key=lambda b: -b["edge"]):
        if per_match.get(b["matchId"], 0) >= MAX_PER_MATCH_TOP:
            continue
        top_bets.append(b)
        per_match[b["matchId"]] = per_match.get(b["matchId"], 0) + 1
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

    # --- Kommande dagar (modellens 1X2 ur listView-odds, inga detaljspel) ---
    upcoming = []
    for d in future_days[:4]:
        rows = []
        for m in sorted(by_day[d], key=lambda m: m["kickoff"]):
            model = MatchModel(m["home"], m["away"], ratings)
            rows.append(match_info(m, model, mss_map))
        upcoming.append({"date": d.isoformat(), "matches": rows})

    results = results_wc.fetch_results()
    headline, summary = build_headline(today_local, day_matches, top_bets)
    push = build_push(today_local, top_bets, day_matches, next_day)

    feed = {
        "schemaVersion": 1,
        "generatedAt": now_utc_iso(),
        "model": {
            "name": "Oscars funderingar (MSS + live-Elo)",
            "version": MODEL_VERSION,
            "eloSource": elo_source,
            "muTotal": MU_TOTAL,
            "mssBlend": MSS_BLEND,
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
        "results": results,
        "push": push,
    }

    os.makedirs(os.path.dirname(FEED_PATH), exist_ok=True)
    os.makedirs(DAYS_DIR, exist_ok=True)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DAYS_DIR, "%s.json" % date_str), "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=1)

    # Fixture-liggare: ackumulera alla listade matcher (för historik/analys)
    fixtures = {}
    if os.path.exists(FIXTURES_PATH):
        try:
            with open(FIXTURES_PATH, encoding="utf-8") as f:
                fixtures = json.load(f)
        except Exception:
            fixtures = {}
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
