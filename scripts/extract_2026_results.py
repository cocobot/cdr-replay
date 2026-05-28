#!/usr/bin/env python3
"""Extract the senior 2026 results from the Coupe de France de Robotique
Google Sheet (tab 'Résultats équipes') into a clean JSON.

  data/coupe2026/sheet.xlsx  ->  data/coupe2026/teams_results.json

Each team: name, type ('legends' | null), rank, scores per série 1..5,
W/L/draw, stats, scores per finale phase (huitièmes → finale_3).
"""

import json
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/coupe2026/sheet.xlsx"
OUT = ROOT / "data/coupe2026/teams_results.json"

# Column indices (1-based, matches openpyxl). Row 2 has the headers.
COLS = {
    "type": 1, "name": 2, "rank": 4, "total": 5,
    "s1": 6, "s2": 7, "s3": 8, "s4": 9, "s5": 10,
    "matchs": 11, "wins": 12, "losses": 13, "draws": 14,
    "avg": 15, "std": 16, "min": 17, "max": 18,
    "huitiemes": 19, "quarts": 20, "semi": 21,
    "petite_finale": 22, "finale_1": 23, "finale_2": 24, "finale_3": 25,
}


def clean(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return v


def main():
    wb = openpyxl.load_workbook(SHEET, data_only=True)
    ws = wb["Résultats  équipes"]      # note: two spaces in the name
    teams = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        name = clean(row[COLS["name"] - 1])
        if not name or name.lower() == "placeholder":
            continue
        t = {
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
            "phases": {
                k: clean(row[COLS[k] - 1])
                for k in ("huitiemes", "quarts", "semi",
                          "petite_finale", "finale_1", "finale_2", "finale_3")
            },
        }
        teams.append(t)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "year": 2026, "category": "senior",
        "source": "https://docs.google.com/spreadsheets/d/1_Y3QtUbTpdOkGfca1YflqOHdvwMGy4sircApoWtClXM/",
        "teams": teams,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    n_qual = sum(1 for t in teams if any(t["phases"][p] is not None for p in t["phases"]))
    n_legends = sum(1 for t in teams if t["type"] == "legends")
    print(f"  {len(teams)} équipes -> {OUT}")
    print(f"  dont {n_qual} en phases finales, {n_legends} Legends")


if __name__ == "__main__":
    main()
