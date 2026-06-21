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
import json, os, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = json.load(open(os.path.join(ROOT, "data", "clv_log.json")))
feed = json.load(open(os.path.join(ROOT, "data", "feed.json")))
results = {frozenset((r["home"], r["away"])): r for r in feed.get("results", [])}

def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()

def settle(e, h, a, hh, ha, scorers):
    m, pick, line, pl = e["market"], e["settlePick"], e.get("settleLine"), e.get("settlePlayer")
    if m == "1X2": return ("1" if h>a else "2" if h<a else "X") == pick
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

def result_for(match):
    try: home, away = [x.strip() for x in match.split("–")]
    except ValueError: return None
    r = results.get(frozenset((home, away)))
    if not r: return None
    if r["home"] == home: return (r["scoreHome"],r["scoreAway"],r.get("htHome"),r.get("htAway"),r.get("scorers") or [])
    return (r["scoreAway"],r["scoreHome"],r.get("htAway"),r.get("htHome"),r.get("scorers") or [])

clv = defaultdict(list); pnl = defaultdict(lambda: [0,0,0.0])  # seg -> [n,wins,profit]
for e in log.values():
    if e["closeOdds"] and e["recOdds"]:
        clv[e["recommendable"]].append(e["recOdds"]/e["closeOdds"] - 1)
        clv[("mkt", e["market"])].append(e["recOdds"]/e["closeOdds"] - 1)
    sc = result_for(e["match"])
    if sc:
        w = settle(e, *sc)
        if w is not None:
            for seg in (("rec", e["recommendable"]), ("mkt2", e["market"])):
                s = pnl[seg]; s[0]+=1; s[1]+=1 if w else 0
                s[2]+= (e["recOdds"]-1) if w else -1   # 1 enhet platt

def avg(xs): return sum(xs)/len(xs) if xs else 0.0
print("=== CLV (recOdds/closeOdds−1) — positivt = slår stängningslinjen ===")
for k in [True, False]:
    xs = clv.get(k, [])
    print("  recommendable=%-5s  n=%3d  snitt-CLV %+5.2f%%" % (k, len(xs), avg(xs)*100))
print("\n  per marknad:")
for k in sorted([k for k in clv if isinstance(k,tuple)], key=lambda k:-avg(clv[k])):
    print("   %-10s n=%3d  CLV %+5.2f%%" % (k[1], len(clv[k]), avg(clv[k])*100))
print("\n=== Skugg-P&L (platt 1 enhet) — rekommenderade vs ej ===")
for k in [True, False]:
    s = pnl.get(("rec", k), [0,0,0.0])
    roi = s[2]/s[0]*100 if s[0] else 0
    print("  recommendable=%-5s  %3d rättade  %2d vinst  ROI %+6.1f%%  resultat %+6.1f" % (k, s[0], s[1], roi, s[2]))
