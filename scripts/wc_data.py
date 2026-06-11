#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Statisk VM 2026-data: de 48 lagen, grupper, flaggor, namn-alias och
fixture-index (samma som vm2026-facit, så results.json kan mappas).

Kanoniskt lagnamn = facit-kortnamnet ("Bosnien", "Curacao", ...). Alla
källor (Kambi, eloratings.net, football-data.org, mss.json) normaliseras
hit via `short_of()`.
"""
import unicodedata

# (grupp, kortnamn, eloratings-namn, flagga)
TEAMS = [
    ("A", "Mexiko",          "Mexico",                 "🇲🇽"),
    ("A", "Sydkorea",        "South Korea",            "🇰🇷"),
    ("A", "Tjeckien",        "Czechia",                "🇨🇿"),
    ("A", "Sydafrika",       "South Africa",           "🇿🇦"),
    ("B", "Kanada",          "Canada",                 "🇨🇦"),
    ("B", "Schweiz",         "Switzerland",            "🇨🇭"),
    ("B", "Qatar",           "Qatar",                  "🇶🇦"),
    ("B", "Bosnien",         "Bosnia and Herzegovina", "🇧🇦"),
    ("C", "Brasilien",       "Brazil",                 "🇧🇷"),
    ("C", "Marocko",         "Morocco",                "🇲🇦"),
    ("C", "Skottland",       "Scotland",               "🏴󠁧󠁢󠁳󠁣󠁴󠁿"),
    ("C", "Haiti",           "Haiti",                  "🇭🇹"),
    ("D", "USA",             "United States",          "🇺🇸"),
    ("D", "Paraguay",        "Paraguay",               "🇵🇾"),
    ("D", "Australien",      "Australia",              "🇦🇺"),
    ("D", "Turkiet",         "Turkey",                 "🇹🇷"),
    ("E", "Tyskland",        "Germany",                "🇩🇪"),
    ("E", "Ecuador",         "Ecuador",                "🇪🇨"),
    ("E", "Elfenbenskusten", "Ivory Coast",            "🇨🇮"),
    ("E", "Curacao",         "Curacao",                "🇨🇼"),
    ("F", "Nederländerna",   "Netherlands",            "🇳🇱"),
    ("F", "Japan",           "Japan",                  "🇯🇵"),
    ("F", "Sverige",         "Sweden",                 "🇸🇪"),
    ("F", "Tunisien",        "Tunisia",                "🇹🇳"),
    ("G", "Belgien",         "Belgium",                "🇧🇪"),
    ("G", "Egypten",         "Egypt",                  "🇪🇬"),
    ("G", "Iran",            "Iran",                   "🇮🇷"),
    ("G", "Nya Zeeland",     "New Zealand",            "🇳🇿"),
    ("H", "Spanien",         "Spain",                  "🇪🇸"),
    ("H", "Uruguay",         "Uruguay",                "🇺🇾"),
    ("H", "Saudiarabien",    "Saudi Arabia",           "🇸🇦"),
    ("H", "Kap Verde",       "Cape Verde",             "🇨🇻"),
    ("I", "Frankrike",       "France",                 "🇫🇷"),
    ("I", "Senegal",         "Senegal",                "🇸🇳"),
    ("I", "Norge",           "Norway",                 "🇳🇴"),
    ("I", "Irak",            "Iraq",                   "🇮🇶"),
    ("J", "Argentina",       "Argentina",              "🇦🇷"),
    ("J", "Österrike",       "Austria",                "🇦🇹"),
    ("J", "Algeriet",        "Algeria",                "🇩🇿"),
    ("J", "Jordanien",       "Jordan",                 "🇯🇴"),
    ("K", "Portugal",        "Portugal",               "🇵🇹"),
    ("K", "DR Kongo",        "DR Congo",               "🇨🇩"),
    ("K", "Uzbekistan",      "Uzbekistan",             "🇺🇿"),
    ("K", "Colombia",        "Colombia",               "🇨🇴"),
    ("L", "England",         "England",                "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    ("L", "Kroatien",        "Croatia",                "🇭🇷"),
    ("L", "Ghana",           "Ghana",                  "🇬🇭"),
    ("L", "Panama",          "Panama",                 "🇵🇦"),
]

# Värdnationerna spelar alla sina matcher på hemmaplan → Elo-bonus i modellen.
HOSTS = {"USA", "Mexiko", "Kanada"}

GROUP_OF = {t[1]: t[0] for t in TEAMS}
FLAG_OF = {t[1]: t[3] for t in TEAMS}
ELO_NAME_OF = {t[1]: t[2] for t in TEAMS}
SHORT_FROM_ELO = {t[2]: t[1] for t in TEAMS}

# Varianter andra källor använder → vårt kortnamn. Kambi (svenska),
# football-data.org (engelska) och eloratings.net täcks.
EXTRA_ALIASES = {
    # Kambi / svenska varianter
    "bosnien hercegovina": "Bosnien", "bosnien och hercegovina": "Bosnien",
    "curacao": "Curacao", "curaçao": "Curacao",
    "elfenbenskusten": "Elfenbenskusten",
    "kap verde": "Kap Verde", "kapverde": "Kap Verde",
    "forenta staterna": "USA", "förenta staterna": "USA",
    "sodkorea": "Sydkorea",
    # Engelska varianter (football-data.org / eloratings)
    "mexico": "Mexiko", "south africa": "Sydafrika", "south korea": "Sydkorea",
    "korea republic": "Sydkorea", "republic of korea": "Sydkorea",
    "czechia": "Tjeckien", "czech republic": "Tjeckien",
    "canada": "Kanada", "switzerland": "Schweiz",
    "bosnia and herzegovina": "Bosnien", "bosnia herzegovina": "Bosnien", "bosnia": "Bosnien",
    "brazil": "Brasilien", "morocco": "Marocko", "scotland": "Skottland",
    "usa": "USA", "united states": "USA", "united states of america": "USA",
    "australia": "Australien", "turkey": "Turkiet", "turkiye": "Turkiet", "türkiye": "Turkiet",
    "germany": "Tyskland", "ivory coast": "Elfenbenskusten",
    "cote d ivoire": "Elfenbenskusten", "côte d'ivoire": "Elfenbenskusten",
    "netherlands": "Nederländerna", "sweden": "Sverige", "tunisia": "Tunisien",
    "belgium": "Belgien", "egypt": "Egypten", "iran": "Iran", "ir iran": "Iran",
    "new zealand": "Nya Zeeland", "spain": "Spanien",
    "saudi arabia": "Saudiarabien", "cape verde": "Kap Verde", "cabo verde": "Kap Verde",
    "cape verde islands": "Kap Verde",
    "france": "Frankrike", "norway": "Norge", "iraq": "Irak",
    "austria": "Österrike", "algeria": "Algeriet", "jordan": "Jordanien",
    "dr congo": "DR Kongo", "congo dr": "DR Kongo",
    "democratic republic of the congo": "DR Kongo",
    "croatia": "Kroatien",
}


# eloratings.net:s World.tsv identifierar lag med 2-bokstavskoder (ISO-aktiga,
# med EN/SC för England/Skottland). Parsern slår upp koderna här.
ELO_CODE2SHORT = {
    "MX": "Mexiko", "KR": "Sydkorea", "CZ": "Tjeckien", "ZA": "Sydafrika",
    "CA": "Kanada", "CH": "Schweiz", "QA": "Qatar", "BA": "Bosnien",
    "BR": "Brasilien", "MA": "Marocko", "SC": "Skottland", "HT": "Haiti",
    "US": "USA", "PY": "Paraguay", "AU": "Australien", "TR": "Turkiet",
    "DE": "Tyskland", "EC": "Ecuador", "CI": "Elfenbenskusten", "CW": "Curacao",
    "NL": "Nederländerna", "JP": "Japan", "SE": "Sverige", "TN": "Tunisien",
    "BE": "Belgien", "EG": "Egypten", "IR": "Iran", "NZ": "Nya Zeeland",
    "ES": "Spanien", "UY": "Uruguay", "SA": "Saudiarabien", "CV": "Kap Verde",
    "FR": "Frankrike", "SN": "Senegal", "NO": "Norge", "IQ": "Irak",
    "AR": "Argentina", "AT": "Österrike", "DZ": "Algeriet", "JO": "Jordanien",
    "PT": "Portugal", "CD": "DR Kongo", "UZ": "Uzbekistan", "CO": "Colombia",
    "EN": "England", "HR": "Kroatien", "GH": "Ghana", "PA": "Panama",
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def _build_alias_map():
    m = {}
    for (_g, short, elo, _f) in TEAMS:
        m[norm(short)] = short
        m[norm(elo)] = short
    for k, short in EXTRA_ALIASES.items():
        m[norm(k)] = short
    return m


ALIAS = _build_alias_map()


def short_of(name):
    """Källnamn (Kambi/football-data/elo) → kanoniskt kortnamn, eller None."""
    return ALIAS.get(norm(name))


def stage_for(home, away, kickoff_iso):
    """Turneringsfas: gruppnamn om lagen delar grupp, annars slutspelsfas
    utifrån datum (spelschemat är känt i förväg)."""
    d = (kickoff_iso or "")[:10]
    gh, ga = GROUP_OF.get(home), GROUP_OF.get(away)
    if gh and gh == ga and (not d or d <= "2026-06-27"):
        # Gruppkollen gäller bara under gruppspelsfönstret: från kvartsfinalen
        # och framåt KAN två lag ur samma grupp mötas igen — då ska datumet,
        # inte gruppen, avgöra fasen (viktigt för progress-bygget i results_wc).
        return "Grupp " + gh
    if d <= "2026-06-27":
        return "Gruppspel"
    if d <= "2026-07-03":
        return "Sextondelsfinal"
    if d <= "2026-07-07":
        return "Åttondelsfinal"
    if d <= "2026-07-11":
        return "Kvartsfinal"
    if d <= "2026-07-15":
        return "Semifinal"
    if d <= "2026-07-18":
        return "Bronsmatch"
    return "Final"
