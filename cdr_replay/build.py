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
import sys
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


def _write_index(tree, teams):
    """(Re)write index.json + teams.json from what's parsed so far."""
    for t in teams:
        teams[t].sort(key=lambda a: (a["year"], a["series"], a["t_start"]))
    teams_meta = sorted((_team_meta(n, apps) for n, apps in teams.items()),
                        key=lambda t: t["name"].lower())
    (DATA / "index.json").write_text(json.dumps(
        {"tree": tree, "teams": teams_meta}, ensure_ascii=False, separators=(",", ":")))
    (DATA / "teams.json").write_text(json.dumps(
        teams, ensure_ascii=False, separators=(",", ":")))


def _git_publish(msg):
    try:
        subprocess.run(["git", "add", "site/data"], cwd=ROOT, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
            subprocess.run(["git", "commit", "-q", "-m", msg], cwd=ROOT, check=True)
            subprocess.run(["git", "push", "-q", "origin", "main"], cwd=ROOT, check=True)
            print(f"  published: {msg}")
    except Exception as e:
        print(f"  (git publish failed: {e})")


def build(config_path="config/videos.yaml", ocr_fps=1.0, workers=0,
          cleanup=False, publish=False, resume=False):
    cfg_path = ROOT / config_path
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    templates = overlay.load_templates(TEMPLATES_NPZ)
    roster = None
    if cfg.get("roster"):
        rp = ROOT / cfg["roster"]
        if rp.exists():
            roster = overlay.load_roster(rp)

    (DATA / "series").mkdir(parents=True, exist_ok=True)
    if resume:                            # keep what's done; only fill the gaps
        ix = DATA / "index.json"
        tree = json.loads(ix.read_text())["tree"] if ix.exists() else {}
        tj = DATA / "teams.json"
        teams = json.loads(tj.read_text()) if tj.exists() else {}
    else:                                 # fresh: drop any previous (demo) data
        for f in (DATA / "series").glob("*.json"):
            f.unlink()
        tree, teams = {}, {}

    for v in cfg["videos"]:
        cat, year, series = v["category"], v["year"], str(v["series"])
        vid = video_id(v["youtube"])
        sl = slug(cat, year, series)
        if resume and (DATA / "series" / f"{sl}.json").exists():
            print(f"[{cat} {year} série {series}] {vid} — déjà fait, skip")
            continue
        print(f"[{cat} {year} série {series}] {vid}")
        try:
            path = ensure_download(v["youtube"])
            cfg = overlay.load_overlay(year)
            matches, duration = parse.parse_video(
                str(path), templates, cfg=cfg, roster=roster,
                ocr_fps=ocr_fps, workers=workers)
        except Exception as e:            # bad download / parse -> skip, keep going
            print(f"  ! échec, on saute: {e}")
            continue
        print(f"  -> {len(matches)} matchs")
        if cleanup:                       # free disk for the next download
            path.unlink(missing_ok=True)
        out = {"category": cat, "year": year, "series": series,
               "video_id": vid, "duration_s": duration, "matches": matches}
        (DATA / "series" / f"{sl}.json").write_text(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")))

        tree.setdefault(cat, {}).setdefault(str(year), {})[series] = len(matches)
        for mi, m in enumerate(matches):
            ref = {"category": cat, "year": year, "series": series, "slug": sl,
                   "video_id": vid, "mi": mi, "t_start": m["t_start"], "t_end": m["t_end"],
                   "table": m["table"]}
            pairs = [("yellow", m["team_yellow"], m["team_blue"], m.get("yellow_city"), m.get("yellow_country")),
                     ("blue", m["team_blue"], m["team_yellow"], m.get("blue_city"), m.get("blue_country"))]
            for color, team, opp, city, country in pairs:
                if team:
                    teams.setdefault(team, []).append(
                        {**ref, "color": color, "opponent": opp, "city": city, "country": country})

        # Keep index/teams consistent with what's parsed; publish after each video.
        _write_index(tree, teams)
        if publish:
            _git_publish(f"data: {cat} {year} série {series} ({len(matches)} matchs)")

    n_series = sum(len(y) for c in tree.values() for y in c.values())
    print(f"\nDone | {n_series} séries, {len(teams)} équipes")

    # Post-process: consolidate OCR variants ↔ sheet canonicals, then join
    # per-match scores from the sheet. Idempotent — safe to re-run on already
    # consolidated data.
    print("\n[post] consolidate team names...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "consolidate_teams.py")],
                   check=False)
    print("\n[post] join sheet scores...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "join_scores.py")],
                   check=False)
    if publish:
        _git_publish("data: consolidate team names + join sheet scores")


def _mode(vals):
    vals = [v for v in vals if v]
    return max(set(vals), key=vals.count) if vals else None


def _is_us(name):
    return overlay._normalize(name) in ("COCOTTER", "COC OTTER")


def _team_meta(name, apps):
    return {"name": name, "city": _mode(a.get("city") for a in apps),
            "cat": _mode(a.get("category") for a in apps), "us": _is_us(name)}
