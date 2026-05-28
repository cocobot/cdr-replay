#!/usr/bin/env python3
"""Join Google-sheet scores onto every video match.

Inputs:
  data/coupe<year>/matches_results.json  (extracted by extract_results.py)
  data/team_aliases.json                 (built by consolidate_teams.py)
  site/data/series/*.json                (video matches, post-consolidation)

For each video match, find the matching sheet entry:
  - same series (or for finales: any finale row)
  - both team names (after aliasing) match the sheet (color-aware when known)
Then writes score_yellow / score_blue / winner / sheet_match_n onto the match.

We process senior only (no junior sheet exists).
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"


def load_sheet_matches(year):
    p = ROOT / f"data/coupe{year}/matches_results.json"
    return json.loads(p.read_text())["matches"] if p.exists() else []


def main():
    alias = json.loads((ROOT / "data/team_aliases.json").read_text())

    def canon(n):
        return alias.get(n, n) if n else n

    n_files = 0
    n_match = 0
    n_join = 0
    per_year = defaultdict(lambda: [0, 0])      # year -> [joined, total]

    for sf in sorted((SITE / "series").glob("senior_*.json")):
        d = json.loads(sf.read_text())
        year = d["year"]
        series = d["series"]                    # "1".."5" or "finales"
        sheet_all = load_sheet_matches(year)
        # Pool of unjoined sheet matches for this series (allows finding by pair
        # even if the video order doesn't match the sheet's N° Match).
        if series == "finales":
            pool = [m for m in sheet_all if m["series"] == "finales"]
        else:
            pool = [m for m in sheet_all if m["series"] == series]
        used = [False] * len(pool)

        for m in d["matches"]:
            n_match += 1
            per_year[year][1] += 1
            ty, tb = canon(m.get("team_yellow")), canon(m.get("team_blue"))
            if not ty or not tb:
                continue
            # Try color-aware match first (only meaningful when sheet has colors).
            chosen = None
            for i, sm in enumerate(pool):
                if used[i] or not sm.get("colors_known"):
                    continue
                if canon(sm.get("team_yellow")) == ty and canon(sm.get("team_blue")) == tb:
                    chosen = i
                    break
            # Fall back to set match (any order, also works for 2024).
            if chosen is None:
                pair = {ty, tb}
                for i, sm in enumerate(pool):
                    if used[i]:
                        continue
                    a = canon(sm.get("team_yellow") or sm.get("team_a"))
                    b = canon(sm.get("team_blue") or sm.get("team_b"))
                    if {a, b} == pair:
                        chosen = i
                        break
            if chosen is None:
                continue
            sm = pool[chosen]
            used[chosen] = True
            # Map scores to yellow/blue based on the sheet side (or matching pair).
            sa = sm.get("score_yellow") if sm.get("colors_known") else sm.get("score_a")
            sb = sm.get("score_blue") if sm.get("colors_known") else sm.get("score_b")
            if sm.get("colors_known"):
                # Sheet's yellow is the video's yellow only when names match in that orientation.
                if canon(sm.get("team_yellow")) == ty:
                    m["score_yellow"], m["score_blue"] = sa, sb
                else:
                    m["score_yellow"], m["score_blue"] = sb, sa
            else:
                # No color info — assign by which side matches.
                a_name = canon(sm.get("team_a"))
                if a_name == ty:
                    m["score_yellow"], m["score_blue"] = sa, sb
                else:
                    m["score_yellow"], m["score_blue"] = sb, sa
            # Winner relative to video sides
            w = sm.get("winner")
            if w in ("yellow", "blue") and sm.get("colors_known"):
                if canon(sm.get("team_yellow")) == ty:
                    m["winner"] = w
                else:
                    m["winner"] = "blue" if w == "yellow" else "yellow"
            elif w in ("a", "b"):
                a_name = canon(sm.get("team_a"))
                winner_name = a_name if w == "a" else canon(sm.get("team_b"))
                m["winner"] = "yellow" if winner_name == ty else "blue"
            if sm.get("phase"):
                m["phase"] = sm["phase"]
            if sm.get("n"):
                m["sheet_n"] = sm["n"]
            n_join += 1
            per_year[year][0] += 1

        sf.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        n_files += 1

    print(f"joined {n_join}/{n_match} video matches across {n_files} senior files")
    for y in sorted(per_year):
        j, t = per_year[y]
        print(f"  {y}: {j}/{t} ({100 * j // max(t, 1)}%)")


if __name__ == "__main__":
    main()
