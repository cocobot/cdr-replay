#!/usr/bin/env python3
"""Per-team consolidation of city/country across all the team's matches.

The per-match country OCR is low-contrast and sometimes snaps wrong
(Brésil/Suisse/Espagne) — but the Coupe de France is overwhelmingly French.
So: each team's city = modal city across its matches; each team's country =
France if it was ever read for that team, else the modal. Rewrites
site/data/teams.json AND every site/data/series/*.json in place.
"""

import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "site" / "data"


def main():
    teams = json.loads((DATA / "teams.json").read_text())

    loc = {}                              # team -> (city, country)
    for name, apps in teams.items():
        cities = Counter(a["city"] for a in apps if a.get("city"))
        countries = Counter(a["country"] for a in apps if a.get("country"))
        city = cities.most_common(1)[0][0] if cities else None
        # The Coupe de France is overwhelmingly French and the per-frame country
        # OCR is unreliable enough that mis-snaps to Brésil/Suisse/Tchéquie are
        # almost always wrong. Default to France for any team that had any read.
        country = "France" if countries else None
        loc[name] = (city, country)

    for name, apps in teams.items():
        c, k = loc[name]
        for a in apps:
            a["city"] = c
            a["country"] = k
    (DATA / "teams.json").write_text(json.dumps(teams, ensure_ascii=False, separators=(",", ":")))

    nfiles, nchanged = 0, 0
    for sf in sorted((DATA / "series").glob("*.json")):
        d = json.loads(sf.read_text())
        ch = False
        for m in d["matches"]:
            for side in ("yellow", "blue"):
                n = m.get(f"team_{side}")
                if n and n in loc:
                    c, k = loc[n]
                    if m.get(f"{side}_city") != c or m.get(f"{side}_country") != k:
                        m[f"{side}_city"] = c
                        m[f"{side}_country"] = k
                        ch = True
        if ch:
            sf.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
            nchanged += 1
        nfiles += 1

    nonfr = sum(1 for c, k in loc.values() if k and k != "France")
    nfr = sum(1 for c, k in loc.values() if k == "France")
    print(f"{len(loc)} équipes — France: {nfr}, autre: {nonfr}")
    print(f"séries: {nchanged}/{nfiles} fichiers mis à jour")


if __name__ == "__main__":
    main()
