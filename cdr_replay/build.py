"""Build the static site data from a video config.

Reads `config/videos.yaml`, downloads each stream (yt-dlp, 720p) if missing,
parses it into matches, and writes the JSON the site consumes:

  site/data/index.json                     navigation tree + team list
  site/data/series/<cat>_<year>_<series>.json   one stream's matches
  site/data/teams.json                     team -> appearances across years
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

from . import overlay, parse

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "videos"
DATA = ROOT / "site" / "data"
TEMPLATES_NPZ = Path(__file__).resolve().parent / "data" / "templates.npz"

YT_ID = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def video_id(url):
    m = YT_ID.search(url)
    return m.group(1) if m else url


def ensure_download(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    vid = video_id(url)
    path = CACHE / f"{vid}.mp4"
    if path.exists():
        return path
    print(f"  downloading {vid}...")
    # Force H.264 (avc1): OpenCV cannot decode the AV1 720p YouTube also offers.
    subprocess.run(
        ["yt-dlp", "-f",
         "bestvideo[height<=720][vcodec^=avc1]/bestvideo[height<=720][ext=webm]/best[height<=720]",
         "--remux-video", "mp4", "--no-progress", "-o", str(path), url],
        check=True)
    return path


def slug(category, year, series):
    return f"{category}_{year}_{re.sub(r'[^A-Za-z0-9]', '', str(series))}"


def build(config_path="config/videos.yaml", ocr_fps=1.0, workers=0):
    cfg_path = ROOT / config_path
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    templates = overlay.load_templates(TEMPLATES_NPZ)
    roster = None
    if cfg.get("roster"):
        rp = ROOT / cfg["roster"]
        if rp.exists():
            roster = overlay.load_roster(rp)

    (DATA / "series").mkdir(parents=True, exist_ok=True)
    tree, teams = {}, {}

    for v in cfg["videos"]:
        cat, year, series = v["category"], v["year"], str(v["series"])
        vid = video_id(v["youtube"])
        print(f"[{cat} {year} série {series}] {vid}")
        path = ensure_download(v["youtube"])
        matches, duration = parse.parse_video(
            str(path), templates, roster=roster, ocr_fps=ocr_fps, workers=workers)
        print(f"  -> {len(matches)} matchs")

        sl = slug(cat, year, series)
        out = {"category": cat, "year": year, "series": series,
               "video_id": vid, "duration_s": duration, "matches": matches}
        (DATA / "series" / f"{sl}.json").write_text(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")))

        tree.setdefault(cat, {}).setdefault(str(year), [])
        if series not in tree[cat][str(year)]:
            tree[cat][str(year)].append(series)

        for m in matches:
            ref = {"category": cat, "year": year, "series": series, "slug": sl,
                   "video_id": vid, "t_start": m["t_start"], "t_end": m["t_end"],
                   "table": m["table"]}
            pairs = [("yellow", m["team_yellow"], m["team_blue"], m.get("yellow_city"), m.get("yellow_country")),
                     ("blue", m["team_blue"], m["team_yellow"], m.get("blue_city"), m.get("blue_country"))]
            for color, team, opp, city, country in pairs:
                if team:
                    teams.setdefault(team, []).append(
                        {**ref, "color": color, "opponent": opp, "city": city, "country": country})

    for cat in tree:
        for year in tree[cat]:
            tree[cat][year].sort(key=lambda s: (s.isdigit() == False, s))
    for t in teams:
        teams[t].sort(key=lambda a: (a["year"], a["series"], a["t_start"]))

    (DATA / "index.json").write_text(json.dumps(
        {"tree": tree, "teams": sorted(teams)}, ensure_ascii=False, separators=(",", ":")))
    (DATA / "teams.json").write_text(json.dumps(
        teams, ensure_ascii=False, separators=(",", ":")))
    print(f"\nWrote {DATA} | {sum(len(v) for c in tree.values() for v in c.values())} séries, "
          f"{len(teams)} équipes")
