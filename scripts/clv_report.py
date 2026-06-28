#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Framåtriktad utvärdering av spelstrategin via CLV-loggen (data/clv_log.json).

Två mått, inget kräver att man "tippat rätt" i efterhand:
  1. CLV (closing line value): slår rekommendationsoddset stängningsoddset?
     Positiv CLV är det mest sample-effektiva beviset på äkta edge.
  2. Skugg-P&L: rättar både rekommenderade OCH ej-rekommenderade spel mot facit
     (data/feed.json results) → bekräftar att exkluderingarna var rätt.

Kör:  python3 scripts/clv_report.py    (efter några matchdagar med data)
"""
import json, os, unicodedata, datetime
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = json.load(open(os.path.join(ROOT, "data", "clv_log.json")))
feed = json.load(open(os.path.join(ROOT, "data", "feed.json")))
# Behåll ALLA resultatinstanser per lagpar — ett par kan mötas två gånger
# (gruppspel + slutspels-rematch) och får inte kollapsa till sista resultatet.
_results_idx = defaultdict(list)
for _r in feed.get("results", []):
    _results_idx[frozenset((_r["home"], _r["away"]))].append(_r)

def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()

def settle(e, h, a, hh, ha, scorers, winner=None):
    m, pick, line, pl = e["market"], e["settlePick"], e.get("settleLine"), e.get("settlePlayer")
    if m == "1X2": return ("1" if h>a else "2" if h<a else "X") == pick
    if m == "ADVANCE" and winner in ("home", "away"): return winner == pick
    if m == "OU" and line is not None: t=h+a; return t>line if pick=="over" else t<line
    if m == "BTTS": b=h>=1 and a>=1; return b if pick=="yes" else not b
    if m == "DC": return {"1X":h>=a,"X2":a>=h,"12":h!=a}.get(pick)
    if m == "TEAM_OU" and line is not None:
        g=h if pick.startswith("home") else a; return g>line if pick.endswith("over") else g<line
    if m == "CS":
        try: ph,pa=map(int,pick.split("-")); return h==ph and a==pa
        except: return None
    if m == "AH" and line is not None:
        hc=h+line>a; return hc if pick=="home" else (not hc if pick=="away" else None)
    if m == "HTFT" and hh is not None:
        return ("%s/%s"%("1" if hh>ha else "2" if hh<ha else "X","1" if h>a else "2" if h<a else "X"))==pick
    if m == "1H_1X2" and hh is not None: return ("1" if hh>ha else "2" if hh<ha else "X")==pick
    if m == "1H_OU" and hh is not None and line is not None: t=hh+ha; return t>line if pick=="over" else t<line
    if m == "PLAYER" and scorers:
        g=sum(s.get("goals",0) for s in scorers if norm(s.get("name"))==norm(pl))
        return g>=1 if pick=="scorer" else (g>=2 if pick=="twoplus" else None)
    return None

def _iso_date(s):
    try:
        return datetime.date.fromisoformat((s or "")[:10])
    except (ValueError, TypeError):
        return None


def _orient(r, home, away):
    """Resultat orienterat till bettets home/away (winner spegelvänds vid behov)."""
    if r["home"] == home:
        return (r["scoreHome"], r["scoreAway"], r.get("htHome"), r.get("htAway"),
                r.get("scorers") or [], r.get("winner"))
    w = r.get("winner")
    w = "away" if w == "home" else ("home" if w == "away" else w)
    return (r["scoreAway"], r["scoreHome"], r.get("htAway"), r.get("htHome"),
            r.get("scorers") or [], w)


def _pick_instance(instances, kickoff):
    """Vid grupp+slutspels-rematch: välj instansen vars datum ligger NÄRMAST
    avsparken. Bakåtkompatibelt: saknas kickoff/daterade instanser → sista
    instansen (gamla beteendet). Lika dag-distans → senaste datumet."""
    if len(instances) == 1:
        return instances[0]
    kd = _iso_date(kickoff)
    dated = [r for r in instances if _iso_date(r.get("date"))]
    if kd and dated:
        return min(dated, key=lambda r: (abs((_iso_date(r["date"]) - kd).days),
                                         -_iso_date(r["date"]).toordinal()))
    return instances[-1]


def result_for(match, kickoff=None):
    try:
        home, away = [x.strip() for x in match.split("–")]
    except ValueError:
        return None
    instances = _results_idx.get(frozenset((home, away)))
    if not instances:
        return None
    return _orient(_pick_instance(instances, kickoff), home, away)

KO_START = "2026-06-28"   # R32-start (stage_for: grupp t.o.m. 06-27) — skiljer KO från grupp (ISO-jämförelse)
clv = defaultdict(list); pnl = defaultdict(lambda: [0,0,0.0])  # seg -> [n,wins,profit]
for e in log.values():
    is_ko = (e.get("kickoff") or "") >= KO_START
    is_kox = e["market"] == "1X2" and e.get("settlePick") == "X"   # oavgjort-pick (KO-1X2-gaten)
    if e["closeOdds"] and e["recOdds"]:
        c = e["recOdds"]/e["closeOdds"] - 1
        clv[e["recommendable"]].append(c)
        clv[("mkt", e["market"])].append(c)
        if is_ko:
            clv[("ko_mkt", e["market"])].append(c)
            if is_kox:
                clv[("ko_x",)].append(c)
    sc = result_for(e["match"], e.get("kickoff"))
    if sc:
        w = settle(e, *sc)
        if w is not None:
            segs = [("rec", e["recommendable"]), ("mkt2", e["market"])]
            if is_ko:
                segs.append(("ko_pnl", e["market"]))
                if is_kox:
                    segs.append(("ko_x_pnl", "X"))
            for seg in segs:
                s = pnl[seg]; s[0]+=1; s[1]+=1 if w else 0
                s[2]+= (e["recOdds"]-1) if w else -1   # 1 enhet platt

def avg(xs): return sum(xs)/len(xs) if xs else 0.0
def gate(n): return "" if n >= 12 else "  [otillräckligt n — ej beslutsgrundande]"

print("=== CLV (recOdds/closeOdds−1) — positivt = slår stängningslinjen ===")
for k in [True, False]:
    xs = clv.get(k, [])
    print("  recommendable=%-5s  n=%3d  snitt-CLV %+5.2f%%" % (k, len(xs), avg(xs)*100))
print("\n  per marknad (alla faser):")
for k in sorted([k for k in clv if isinstance(k, tuple) and k[0] == "mkt"], key=lambda k:-avg(clv[k])):
    print("   %-10s n=%3d  CLV %+5.2f%%%s" % (k[1], len(clv[k]), avg(clv[k])*100, gate(len(clv[k]))))

# Slutspels-vy (kickoff >= R32-start) — isolerar KO så grupp-data inte blandas in.
ko_keys = sorted([k for k in clv if isinstance(k, tuple) and k[0] == "ko_mkt"], key=lambda k:-avg(clv[k]))
if ko_keys or clv.get(("ko_x",)):
    print("\n  KO-fas hittills (slutspel):")
    for k in ko_keys:
        print("   %-10s n=%3d  CLV %+5.2f%%%s" % (k[1], len(clv[k]), avg(clv[k])*100, gate(len(clv[k]))))
    xs = clv.get(("ko_x",), [])
    if xs:
        print("   %-10s n=%3d  CLV %+5.2f%%%s   (KO-1X2-gate: aktivera bara om CLV>+1.5%% & n>=12 & ROI>=0)"
              % ("1X2 (X)", len(xs), avg(xs)*100, gate(len(xs))))

print("\n=== Skugg-P&L (platt 1 enhet) — rekommenderade vs ej ===")
for k in [True, False]:
    s = pnl.get(("rec", k), [0,0,0.0])
    roi = s[2]/s[0]*100 if s[0] else 0
    print("  recommendable=%-5s  %3d rättade  %2d vinst  ROI %+6.1f%%  resultat %+6.1f" % (k, s[0], s[1], roi, s[2]))

print("\n  per marknad (settlad P&L):")
for k in sorted([k for k in pnl if isinstance(k, tuple) and k[0] == "mkt2"], key=lambda k: pnl[k][2]):
    s = pnl[k]; roi = s[2]/s[0]*100 if s[0] else 0
    print("   %-10s %3d rättade  %2d vinst  ROI %+6.1f%%  resultat %+6.1f%s"
          % (k[1], s[0], s[1], roi, s[2], gate(s[0])))

ko_pnl = sorted([k for k in pnl if isinstance(k, tuple) and k[0] == "ko_pnl"], key=lambda k: pnl[k][2])
xs = pnl.get(("ko_x_pnl", "X"))
if ko_pnl or xs:
    print("\n  KO-fas settlad P&L (slutspel):")
    for k in ko_pnl:
        s = pnl[k]; roi = s[2]/s[0]*100 if s[0] else 0
        print("   %-10s %3d rättade  %2d vinst  ROI %+6.1f%%  resultat %+6.1f%s"
              % (k[1], s[0], s[1], roi, s[2], gate(s[0])))
    if xs:
        roi = xs[2]/xs[0]*100 if xs[0] else 0
        print("   %-10s %3d rättade  %2d vinst  ROI %+6.1f%%  resultat %+6.1f%s   (KO-1X2-gate)"
              % ("1X2 (X)", xs[0], xs[1], roi, xs[2], gate(xs[0])))
