#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skickar morgonens push-notis via Firebase Cloud Messaging (HTTP v1).

Körs av GitHub Action-steget kl 06:00 UTC (08:00 svensk sommartid), EFTER att
generate.py skrivit data/feed.json — notisens titel/innehåll ligger färdiga i
feedens "push"-fält.

Ingen inloggning i appen: alla installationer prenumererar på FCM-topicen
`daily-report`, så ett enda topic-utskick når alla enheter.

Kräver:
  env FCM_SERVICE_ACCOUNT — hela service-account-JSON:en (GitHub secret)
  pip install google-auth requests   (görs i workflow-steget)
"""
import json
import os
import sys

try:
    import requests
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
TOPIC = "daily-report"
SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


def main():
    if not HAVE_DEPS:
        print("google-auth/requests saknas — kör `pip install google-auth requests` "
              "(workflow-steget gör det automatiskt). Hoppar över push.")
        return 0
    raw = os.environ.get("FCM_SERVICE_ACCOUNT", "").strip()
    if not raw:
        print("FCM_SERVICE_ACCOUNT saknas — hoppar över push (sätt repo-secreten "
              "när Firebase-projektet är klart).")
        return 0

    info = json.loads(raw)
    project_id = info.get("project_id")
    if not project_id:
        print("service-account-JSON saknar project_id", file=sys.stderr)
        return 1

    with open(FEED_PATH, encoding="utf-8") as f:
        feed = json.load(f)
    push = feed.get("push") or {}
    title, body = push.get("title"), push.get("body")
    if not title:
        print("Ingen push-text i feeden — inget att skicka.")
        return 0

    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    creds.refresh(Request())

    msg = {
        "message": {
            "topic": TOPIC,
            "notification": {"title": title, "body": body},
            "apns": {
                "payload": {"aps": {"sound": "default", "badge": 1}},
            },
            "data": {"date": (feed.get("day") or {}).get("date") or ""},
        }
    }
    url = "https://fcm.googleapis.com/v1/projects/%s/messages:send" % project_id
    r = requests.post(url, json=msg, timeout=30,
                      headers={"Authorization": "Bearer %s" % creds.token})
    if r.status_code != 200:
        print("FCM-fel %s: %s" % (r.status_code, r.text[:400]), file=sys.stderr)
        return 1
    print("Push skickad till topic %r: %s — %s" % (TOPIC, title, body[:100]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
