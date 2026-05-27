#!/usr/bin/env python3
"""Generate DEMO (fake) site data so the site can be reviewed before real parsing.

Overwritten by `python -m cdr_replay build` once videos are parsed for real.
Teams recur across years so the "matchs d'une équipe à travers les ans" view is
populated. Embeds reuse the few real YouTube ids we have so videos load.
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
random.seed(7)

VIDS = ["ISvunlsdgDo", "jrfmvH_gVxM", "sQ4mJ8B3J3o", "cMHJf1s85q4"]  # real ids -> embeds load

SENIOR = [l.strip() for l in (ROOT / "config/teams.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
JUNIOR = ["Les Petits Bots", "RoboLycée", "Mini Watt", "Cogip Junior", "Les Engrenages",
          "TechnoKids", "Robot'Col", "Volt Académie", "Les Automates", "Pixel Méca",
          "Servo Squad", "Boulons & Co", "Les Roues Libres", "Capteurs Fous",
          "Junior Spark", "Méca Mômes", "Bit & Boulon", "Les Disjoncteurs"]

CITIES = ["Paris", "Lyon", "Toulouse", "Bordeaux", "Nantes", "Lille", "Amiens",
          "Grenoble", "Rennes", "Strasbourg", "Nice", "Montpellier", "Brest",
          "Clermont-Ferrand", "Orléans", "Le Mans", "Vannes", "Cachan", "Riom"]
CITY = {}  # team -> (city, country), stable
def _loc(team):
    if team not in CITY:
        c = CITIES[abs(hash(team)) % len(CITIES)]
        country = "Belgique" if abs(hash(team)) % 11 == 0 else "France"
        CITY[team] = (c, country)
    return CITY[team]

STRUCT = {
    "senior": {2024: ["1", "2", "3", "4", "5", "finales"],
               2025: ["1", "2", "3", "4", "5", "finales"],
               2026: ["1", "2", "3", "4", "5", "finales"]},
    "junior": {2025: ["1", "2", "3", "finales"],
               2026: ["1", "2", "3", "finales"]},
}


def gen_matches(pool, n):
    teams = random.sample(pool, min(len(pool), n * 2))
    t = random.randint(120, 320)
    out = []
    for i in range(min(n, len(teams) // 2)):
        dur = random.randint(95, 150)
        y, b = teams[2 * i], teams[2 * i + 1]
        (yc, yk), (bc, bk) = _loc(y), _loc(b)
        out.append({"table": str(random.randint(1, 6)),
                    "team_yellow": y, "team_blue": b,
                    "yellow_city": yc, "yellow_country": yk,
                    "blue_city": bc, "blue_country": bk,
                    "t_start": float(t), "t_end": float(t + dur)})
        t += dur + random.randint(120, 260)
    return out


def main():
    (DATA / "series").mkdir(parents=True, exist_ok=True)
    tree, teams_idx, vi = {}, {}, 0
    for cat, years in STRUCT.items():
        pool = SENIOR if cat == "senior" else JUNIOR
        for year, series in years.items():
            for s in series:
                matches = gen_matches(pool, 6 if s != "finales" else 4)
                vid = VIDS[vi % len(VIDS)]; vi += 1
                sl = f"{cat}_{year}_{s}"
                (DATA / "series" / f"{sl}.json").write_text(json.dumps(
                    {"category": cat, "year": year, "series": s, "video_id": vid,
                     "duration_s": 7200.0, "matches": matches},
                    ensure_ascii=False, separators=(",", ":")))
                tree.setdefault(cat, {}).setdefault(str(year), {})[s] = len(matches)
                for mi, m in enumerate(matches):
                    ref = {"category": cat, "year": year, "series": s, "slug": sl,
                           "video_id": vid, "mi": mi, "t_start": m["t_start"], "t_end": m["t_end"],
                           "table": m["table"]}
                    for color, team, opp, cy, ck in [
                            ("yellow", m["team_yellow"], m["team_blue"], m["yellow_city"], m["yellow_country"]),
                            ("blue", m["team_blue"], m["team_yellow"], m["blue_city"], m["blue_country"])]:
                        teams_idx.setdefault(team, []).append(
                            {**ref, "color": color, "opponent": opp, "city": cy, "country": ck})

    for t in teams_idx:
        teams_idx[t].sort(key=lambda a: (a["year"], a["series"], a["t_start"]))
    def is_us(n): return n.lower().replace("'", "").replace(" ", "") == "cocotter"
    teams_meta = sorted(
        ({"name": t, "city": _loc(t)[0], "cat": teams_idx[t][0]["category"], "us": is_us(t)}
         for t in teams_idx), key=lambda x: x["name"].lower())
    (DATA / "index.json").write_text(json.dumps(
        {"tree": tree, "teams": teams_meta, "demo": True},
        ensure_ascii=False, separators=(",", ":")))
    (DATA / "teams.json").write_text(json.dumps(teams_idx, ensure_ascii=False, separators=(",", ":")))
    print(f"demo data: {sum(len(v) for c in tree.values() for v in c.values())} séries, "
          f"{len(teams_idx)} équipes")


if __name__ == "__main__":
    main()
