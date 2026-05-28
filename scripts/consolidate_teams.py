#!/usr/bin/env python3
"""Consolidate team names across OCR variants ↔ Google-sheet canonical names.

Pipeline:
  1. Build canonical roster:
       - senior: union of all senior 'teams_results.json' (sheet is truth)
       - junior: no sheet; we cluster video names against each other
  2. For each name found in OCR (site/data/teams.json, every series JSON, and
     the sheet match list), pick a canonical:
       - exact normalized match (teamKey) → take the sheet name
       - fuzzy match (SequenceMatcher >= 0.86 on teamKey) → take that one
       - token overlap (one full word ≥4 chars shared) AND fuzzy >= 0.7
         → take that one
       - else: stays as-is (its own canonical), and OCR variants of the same
         name get clustered together (most frequent spelling wins)
  3. Optional override at data/team_aliases_override.json
       — {"variant": "Canonical Name"}
  4. Rewrite site/data/teams.json (merging entries) and site/data/series/*.json
     (rewriting team names), and write data/team_aliases.json (the resolved
     map, for reproducibility).
"""

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"


def teamkey(name):
    if not name:
        return ""
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def tokens(name):
    """Significant tokens (len>=4, alphabetic, normalized)."""
    s = unicodedata.normalize("NFD", name or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    out = []
    for t in re.split(r"[^a-z0-9]+", s.lower()):
        if len(t) >= 4 and t.isalpha():
            out.append(t)
    return set(out)


def fuzzy(a, b):
    return SequenceMatcher(None, teamkey(a), teamkey(b)).ratio()


def load_canon_senior():
    """canonical sheet names per (category, year). Senior only — sheet only."""
    canon = {}                                  # (cat, year) -> [names]
    for yr in (2024, 2025, 2026):
        p = ROOT / f"data/coupe{yr}/teams_results.json"
        if p.exists():
            canon[("senior", yr)] = [t["name"] for t in json.loads(p.read_text())["teams"]]
    return canon


def collect_video_names():
    """All OCR-detected names, grouped by (cat, year), with occurrence counts."""
    teams = json.loads((SITE / "teams.json").read_text())
    by_cy = defaultdict(Counter)                # (cat, year) -> Counter(name)
    for name, apps in teams.items():
        for a in apps:
            by_cy[(a["category"], a["year"])][name] += 1
    return teams, by_cy


def resolve_one(name, canon_list):
    """Find best canonical from canon_list for `name`. None if no good match."""
    if not name or not canon_list:
        return None
    k = teamkey(name)
    if not k:
        return None
    # 1) exact normalized
    for c in canon_list:
        if teamkey(c) == k:
            return c
    # 2) high fuzzy
    best = max(canon_list, key=lambda c: fuzzy(name, c))
    r = fuzzy(name, best)
    if r >= 0.86:
        return best
    # 3) shared long token + decent fuzzy
    n_tok = tokens(name)
    if n_tok:
        for c in canon_list:
            if n_tok & tokens(c) and fuzzy(name, c) >= 0.70:
                return c
    return None


def cluster_orphans(names_with_counts):
    """Cluster OCR variants without a sheet match. Most frequent spelling wins.

    `names_with_counts` is a list of (name, count). Returns {name -> canonical}.
    """
    items = sorted(names_with_counts, key=lambda x: -x[1])    # most seen first
    clusters = []                       # list of (canonical, [members])
    for name, _ in items:
        if not teamkey(name):
            continue
        placed = False
        for i, (canon, members) in enumerate(clusters):
            if fuzzy(name, canon) >= 0.88 or (
                tokens(name) & tokens(canon) and fuzzy(name, canon) >= 0.78
            ):
                clusters[i][1].append(name)
                placed = True
                break
        if not placed:
            clusters.append((name, [name]))
    out = {}
    for canon, members in clusters:
        for m in members:
            out[m] = canon
    return out


def main():
    canon = load_canon_senior()
    teams, by_cy = collect_video_names()

    overrides_path = ROOT / "data/team_aliases_override.json"
    overrides = (json.loads(overrides_path.read_text())
                 if overrides_path.exists() else {})

    # Senior canonical pool: year-local first (preferred), then cross-year.
    # Rationale: rosters change between editions, so a video frame from 2026
    # should map to the 2026 sheet name (e.g. "Team Opossums") rather than the
    # 2024 "Opossums" which is a distinct entry.
    canon_all_senior = sorted({n for (c, _), L in canon.items()
                               if c == "senior" for n in L})
    # Resolve every video name -> canonical
    alias = {}                                  # name -> canonical
    stats = {"exact_sheet": 0, "fuzzy_sheet": 0, "orphan_cluster": 0, "override": 0}
    for (cat, yr), counts in by_cy.items():
        year_local = canon.get((cat, yr), [])
        cross_year = [n for n in canon_all_senior if n not in year_local]
        unresolved = []
        for name, c in counts.items():
            if name in overrides:
                alias[name] = overrides[name]
                stats["override"] += 1
                continue
            r = resolve_one(name, year_local) or resolve_one(name, cross_year)
            if r:
                alias[name] = r
                if teamkey(name) == teamkey(r):
                    stats["exact_sheet"] += 1
                else:
                    stats["fuzzy_sheet"] += 1
            else:
                unresolved.append((name, c))
        # cluster what's left
        if unresolved:
            cmap = cluster_orphans(unresolved)
            for k, v in cmap.items():
                alias[k] = v
                stats["orphan_cluster"] += 1

    # Sheet names also get registered as self-aliases so the joiner can look
    # them up unchanged.
    for cy_list in canon.values():
        for n in cy_list:
            alias.setdefault(n, n)

    # --- Rewrite teams.json: merge appearances under canonical name -----------
    new_teams = defaultdict(list)
    for name, apps in teams.items():
        cn = alias.get(name, name)
        for a in apps:
            new_a = dict(a)
            if a.get("opponent") in alias:
                new_a["opponent"] = alias[a["opponent"]]
            new_teams[cn].append(new_a)
    # de-dup by (slug, mi): same match might exist under both name variants
    deduped = {}
    for cn, apps in new_teams.items():
        seen = set()
        keep = []
        for a in apps:
            k = (a.get("slug"), a.get("mi"), a.get("opponent"))
            if k in seen:
                continue
            seen.add(k)
            keep.append(a)
        deduped[cn] = keep
    (SITE / "teams.json").write_text(
        json.dumps(deduped, ensure_ascii=False, separators=(",", ":")))

    # --- Rewrite every series JSON --------------------------------------------
    n_files, n_renamed = 0, 0
    for sf in sorted((SITE / "series").glob("*.json")):
        d = json.loads(sf.read_text())
        ch = False
        for m in d["matches"]:
            for side in ("yellow", "blue"):
                n = m.get(f"team_{side}")
                if n and alias.get(n, n) != n:
                    m[f"team_{side}"] = alias[n]
                    ch = True
                    n_renamed += 1
        if ch:
            sf.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        n_files += 1

    # --- Persist alias map ----------------------------------------------------
    out = ROOT / "data/team_aliases.json"
    out.write_text(json.dumps(dict(sorted(alias.items())),
                              ensure_ascii=False, indent=2))

    print(f"alias entries: {len(alias)}")
    print(f"  {stats}")
    print(f"teams.json: {len(teams)} → {len(deduped)} canonical names")
    print(f"series files: {n_renamed} renames across {n_files} files")
    print(f"-> {out.relative_to(ROOT)}")

    # Sanity print: list "fuzzy_sheet" matches so the user can spot-check
    fuzzy_pairs = [(n, c) for n, c in alias.items()
                   if c in {x for L in canon.values() for x in L}
                   and teamkey(n) != teamkey(c)]
    if fuzzy_pairs:
        print("\nFuzzy → sheet name (review):")
        for n, c in sorted(fuzzy_pairs):
            print(f"  {n!r}  →  {c!r}")


if __name__ == "__main__":
    main()
