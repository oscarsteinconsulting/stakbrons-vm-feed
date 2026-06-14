#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Svenska TV-kanaler för VM 2026. SVT och TV4 delar rättigheterna och alla 104
matcher visas gratis (SVT1/SVT2/SVT Play resp. TV4/TV4 Play). Vi anger
huvudkanalen SVT eller TV4 per match.

Källa: publicerat SVT/TV4-gruppspelsschema (juni 2026). Nyckel = oordnat lagpar
med wc_data:s kortnamn (matchens home/away är redan normaliserade dit i
generatorn). Endast GRUPPSPELET är annonserat per kanal — slutspelsmatcher
saknas tills SVT/TV4 satt kanal, och channel_for() returnerar då None
(appen visar då ingen kanal-markering).
"""

# (home, away, channel) — ordningen i paret spelar ingen roll, uppslag sker på
# frozenset. Kanaler enligt det publicerade gruppspelsschemat.
GROUP_STAGE = [
    # Grupp A
    ("Mexiko", "Sydafrika", "TV4"),
    ("Sydkorea", "Tjeckien", "TV4"),
    ("Tjeckien", "Sydafrika", "TV4"),
    ("Mexiko", "Sydkorea", "TV4"),
    ("Sydafrika", "Sydkorea", "SVT"),
    ("Tjeckien", "Mexiko", "SVT"),
    # Grupp B
    ("Kanada", "Bosnien", "SVT"),
    ("Qatar", "Schweiz", "TV4"),
    ("Schweiz", "Bosnien", "TV4"),
    ("Kanada", "Qatar", "TV4"),
    ("Schweiz", "Kanada", "TV4"),
    ("Bosnien", "Qatar", "TV4"),
    # Grupp C
    ("Brasilien", "Marocko", "SVT"),
    ("Haiti", "Skottland", "SVT"),
    ("Skottland", "Marocko", "SVT"),
    ("Brasilien", "Haiti", "TV4"),
    ("Marocko", "Haiti", "TV4"),
    ("Skottland", "Brasilien", "TV4"),
    # Grupp D
    ("USA", "Paraguay", "TV4"),
    ("Australien", "Turkiet", "TV4"),
    ("USA", "Australien", "SVT"),
    ("Turkiet", "Paraguay", "TV4"),
    ("Turkiet", "USA", "TV4"),
    ("Paraguay", "Australien", "TV4"),
    # Grupp E
    ("Tyskland", "Curacao", "TV4"),
    ("Elfenbenskusten", "Ecuador", "TV4"),
    ("Tyskland", "Elfenbenskusten", "TV4"),
    ("Ecuador", "Curacao", "TV4"),
    ("Curacao", "Elfenbenskusten", "SVT"),
    ("Ecuador", "Tyskland", "SVT"),
    # Grupp F
    ("Nederländerna", "Japan", "TV4"),
    ("Sverige", "Tunisien", "SVT"),
    ("Nederländerna", "Sverige", "TV4"),
    ("Tunisien", "Japan", "SVT"),
    ("Tunisien", "Nederländerna", "SVT"),
    ("Sverige", "Japan", "SVT"),
    # Grupp G
    ("Belgien", "Egypten", "SVT"),
    ("Iran", "Nya Zeeland", "TV4"),
    ("Belgien", "Iran", "TV4"),
    ("Nya Zeeland", "Egypten", "TV4"),
    ("Egypten", "Iran", "TV4"),
    ("Nya Zeeland", "Belgien", "TV4"),
    # Grupp H
    ("Spanien", "Kap Verde", "SVT"),
    ("Saudiarabien", "Uruguay", "TV4"),
    ("Spanien", "Saudiarabien", "TV4"),
    ("Uruguay", "Kap Verde", "TV4"),
    ("Kap Verde", "Saudiarabien", "TV4"),
    ("Uruguay", "Spanien", "TV4"),
    # Grupp I
    ("Frankrike", "Senegal", "SVT"),
    ("Irak", "Norge", "TV4"),
    ("Frankrike", "Irak", "TV4"),
    ("Norge", "Senegal", "SVT"),
    ("Norge", "Frankrike", "TV4"),
    ("Senegal", "Irak", "TV4"),
    # Grupp J
    ("Argentina", "Algeriet", "TV4"),
    ("Österrike", "Jordanien", "TV4"),
    ("Argentina", "Österrike", "SVT"),
    ("Jordanien", "Algeriet", "TV4"),
    ("Argentina", "Jordanien", "TV4"),
    ("Österrike", "Algeriet", "TV4"),
    # Grupp K
    ("Portugal", "DR Kongo", "TV4"),
    ("Uzbekistan", "Colombia", "TV4"),
    ("Portugal", "Uzbekistan", "SVT"),
    ("Colombia", "DR Kongo", "SVT"),
    ("Portugal", "Colombia", "TV4"),
    ("Uzbekistan", "DR Kongo", "TV4"),
    # Grupp L
    ("England", "Kroatien", "TV4"),
    ("Ghana", "Panama", "TV4"),
    ("England", "Ghana", "SVT"),
    ("Panama", "Kroatien", "TV4"),
    ("Panama", "England", "SVT"),
    ("Kroatien", "Ghana", "SVT"),
]

CHANNEL_OF = {frozenset((h, a)): ch for h, a, ch in GROUP_STAGE}


def channel_for(home, away):
    """Svensk TV-kanal ('SVT'/'TV4') för matchen, eller None om okänd
    (slutspel innan kanal annonserats)."""
    return CHANNEL_OF.get(frozenset((home, away)))


def _selftest():
    # Inga dubblettpar.
    assert len(CHANNEL_OF) == len(GROUP_STAGE), "dubblett-lagpar i GROUP_STAGE"
    # Exakt 72 gruppspelsmatcher.
    assert len(GROUP_STAGE) == 72, "förväntade 72 gruppspelsmatcher, fick %d" % len(GROUP_STAGE)
    # Varje lag spelar exakt 3 gruppspelsmatcher.
    from collections import Counter
    c = Counter()
    for h, a, _ in GROUP_STAGE:
        c[h] += 1
        c[a] += 1
    bad = {team: n for team, n in c.items() if n != 3}
    assert not bad, "lag med fel antal matcher (ska vara 3): %s" % bad
    assert len(c) == 48, "förväntade 48 lag, fick %d" % len(c)
    # Bara giltiga kanaler.
    assert all(ch in ("SVT", "TV4") for _, _, ch in GROUP_STAGE), "ogiltig kanal"
    print("tv_channels självtest OK: 72 matcher, 48 lag × 3, kanaler SVT/TV4")


if __name__ == "__main__":
    _selftest()
