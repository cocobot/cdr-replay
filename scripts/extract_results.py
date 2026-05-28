#!/usr/bin/env python3
"""Extract senior results from the Coupe de France de Robotique Google Sheet
(tab 'Résultats équipes') into a clean JSON, for any year.

Usage: python scripts/extract_results.py <year>
       expects   data/coupe<year>/sheet.xlsx
       writes    data/coupe<year>/teams_results.json
"""

import json
import sys
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parent.parent

# Column indices (1-based). Row 2 has the headers; data starts row 3 (row 3 is
# a 'Placeholder' line in 2026, skipped via the name check).
COLS = {
    "type": 1, "name": 2, "rank": 4, "total": 5,
    "s1": 6, "s2": 7, "s3": 8, "s4": 9, "s5": 10,
    "matchs": 11, "wins": 12, "losses": 13, "draws": 14,
    "avg": 15, "std": 16, "min": 17, "max": 18,
    "huitiemes": 19, "quarts": 20, "semi": 21,
    "petite_finale": 22, "finale_1": 23, "finale_2": 24, "finale_3": 25,
}
PHASES = ("huitiemes", "quarts", "semi", "petite_finale",
          "finale_1", "finale_2", "finale_3")


def clean(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return v


def extract(year):
    sheet = ROOT / f"data/coupe{year}/sheet.xlsx"
    out = ROOT / f"data/coupe{year}/teams_results.json"
    wb = openpyxl.load_workbook(sheet, data_only=True)
    ws = wb["Résultats  équipes"]            # tab name has TWO spaces
    teams = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        name = clean(row[COLS["name"] - 1])
        if not name or name.lower() == "placeholder":
            continue
        teams.append({
            "name": name,
            "type": "legends" if clean(row[COLS["type"] - 1]) == "Legends" else None,
            "rank": clean(row[COLS["rank"] - 1]),
            "score_total": clean(row[COLS["total"] - 1]),
            "scores": [clean(row[COLS[f"s{i}"] - 1]) for i in range(1, 6)],
            "matches": clean(row[COLS["matchs"] - 1]),
            "wins": clean(row[COLS["wins"] - 1]),
            "losses": clean(row[COLS["losses"] - 1]),
            "draws": clean(row[COLS["draws"] - 1]),
            "score_avg": clean(row[COLS["avg"] - 1]),
            "score_std": clean(row[COLS["std"] - 1]),
            "score_min": clean(row[COLS["min"] - 1]),
            "score_max": clean(row[COLS["max"] - 1]),
            "phases": {p: clean(row[COLS[p] - 1]) for p in PHASES},
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "year": year, "category": "senior", "teams": teams,
    }, ensure_ascii=False, indent=2))
    n_phases = sum(1 for t in teams if any(t["phases"][p] is not None for p in PHASES))
    n_legends = sum(1 for t in teams if t["type"] == "legends")
    print(f"[{year}] {len(teams)} équipes, {n_phases} en phases finales, "
          f"{n_legends} Legends -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    extract(int(sys.argv[1]))
