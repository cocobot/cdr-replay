"""Parse one stream video into a list of matches.

Pipeline (overlay-driven, no robot tracking):
  1. Sample frames at `ocr_fps`. On each, only run OCR if the match banner is
     present (skips replays / stage shots / transitions -> no false matches).
  2. Read table number, both team names and the countdown from the overlay.
  3. Segment into matches by the (temporally smoothed) table number; within a
     match, resolve the two teams by majority vote over the reads and merge
     fragments split by a cutaway. Optionally snap names to a roster.

A match = {table, team_yellow, team_blue, t_start, t_end}.
"""

from __future__ import annotations

import multiprocessing as mp
from collections import Counter
from difflib import SequenceMatcher

import cv2

from . import overlay
from .overlay import OverlayConfig

# Segmentation tuning
TABLE_SMOOTH_W = 4        # samples each side for table majority smoothing
MATCH_BRIDGE_S = 6.0      # bridge table gaps within a match
MATCH_MIN_S = 8.0         # drop matches shorter than this
MERGE_GAP_S = 180.0       # merge same-table same-teams fragments within this gap
SNAP_MIN = 0.55           # min roster-snap score to apply a snapped name
PRE_ROLL_S = 3.0          # start the clip this many seconds before the countdown

# Set per worker via the Pool initializer (works under fork and spawn alike).
_TEMPLATES = None
_CFG = None


def _init_worker(templates, cfg):
    global _TEMPLATES, _CFG
    _TEMPLATES, _CFG = templates, cfg


def _sample_chunk(args):
    start, end, video, step, fps = args
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    out = []
    idx = start
    while idx < end:
        if idx % step:                     # not a sample: skip cheaply (no decode-to-BGR)
            if not cap.grab():
                break
            idx += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        if overlay.banner_present(frame, _CFG):
            rec = {
                "t": round(idx / fps, 2),
                "table": overlay.read_table(frame, _CFG),
                "yellow": overlay.read_team(frame, "yellow", _TEMPLATES, _CFG),
                "blue": overlay.read_team(frame, "blue", _TEMPLATES, _CFG),
                "timer": overlay.read_timer(frame, _TEMPLATES, _CFG),
            }
            # City/country are constant per match -> read them on 1 OCR sample in 3
            # (Tesseract is the bottleneck; the per-match vote needs only a few).
            if (idx // step) % 3 == 0:
                rec["city_y"] = overlay.read_city(frame, "yellow", _CFG)
                rec["country_y"] = overlay.read_country_raw(frame, "yellow", _CFG)
                rec["city_b"] = overlay.read_city(frame, "blue", _CFG)
                rec["country_b"] = overlay.read_country_raw(frame, "blue", _CFG)
            out.append(rec)
        idx += 1
    cap.release()
    return out


def _sample(video, templates, cfg, ocr_fps, workers):
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    step = max(1, int(round(fps / ocr_fps)))
    n = workers or min(mp.cpu_count(), 12)
    csize = total // n
    chunks = [(i * csize, (i + 1) * csize if i < n - 1 else total, video, step, fps)
              for i in range(n)]
    if n == 1:
        _init_worker(templates, cfg)
        results = [_sample_chunk(chunks[0])]
    else:
        with mp.Pool(n, initializer=_init_worker, initargs=(templates, cfg)) as pool:
            results = pool.map(_sample_chunk, chunks)
    samples = [s for r in results for s in r]
    samples.sort(key=lambda s: s["t"])
    return samples, fps, total


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def _smooth_table(samples):
    tables = [s["table"] for s in samples]
    out = []
    n = len(tables)
    for i in range(n):
        lo, hi = max(0, i - TABLE_SMOOTH_W), min(n, i + TABLE_SMOOTH_W + 1)
        votes = Counter(t for t in tables[lo:hi] if t)
        out.append(votes.most_common(1)[0][0] if votes else None)
    return out


def _cluster(counter):
    clusters = []
    for name, cnt in counter.most_common():
        for cl in clusters:
            if SequenceMatcher(None, name, cl["rep"]).ratio() > 0.8:
                cl["members"].add(name); cl["total"] += cnt
                break
        else:
            clusters.append({"rep": name, "members": {name}, "total": cnt})
    return sorted(clusters, key=lambda c: -c["total"])


def _mode_city(reads):
    reads = [r for r in reads if r]
    if not reads:
        return None
    clusters = _cluster(Counter(reads))
    return clusters[0]["rep"] if clusters else None


def _mode_country(reads):
    snapped = [overlay.snap_country(r) for r in reads if r]
    snapped = [s for s in snapped if s]
    return Counter(snapped).most_common(1)[0][0] if snapped else None


def _resolve_pair(ys, bs, tail=15):
    """Return (yellow_cluster, blue_cluster) of the two teams. Colour assignment
    follows the LATEST overlay state (broadcasters fix a wrong banner mid-match)."""
    ysf = [r for r in ys if r]
    bsf = [r for r in bs if r]
    clusters = _cluster(Counter(ysf) + Counter(bsf))
    if not clusters:
        return None, None
    if len(clusters) == 1:
        return clusters[0], None
    ca, cb = clusters[0], clusters[1]
    recent = ysf[-tail:]
    a = sum(1 for r in recent if r in ca["members"])
    b = sum(1 for r in recent if r in cb["members"])
    return (ca, cb) if a >= b else (cb, ca)


def _loc_for(cluster, team_cities, team_countries):
    """City/country of a team, gathered by the team NAME read (side-independent,
    so a mid-match left/right swap doesn't mix the two teams' cities)."""
    if not cluster:
        return None, None
    cities, countries = [], []
    for tr in cluster["members"]:
        cities += team_cities.get(tr, [])
        countries += team_countries.get(tr, [])
    return _mode_city(cities), _mode_country(countries)


def _same_pair(a, b):
    pa = [x for x in (a["team_yellow"], a["team_blue"]) if x]
    pb = [x for x in (b["team_yellow"], b["team_blue"]) if x]
    if not pa or not pb:
        return False
    close = lambda x, s: any(SequenceMatcher(None, x, y).ratio() > 0.8 for y in s)
    return all(close(x, pb) for x in pa) and all(close(y, pa) for y in pb)


def _merge_fragments(matches):
    merged = []
    for m in matches:
        cand = None
        for p in merged:
            if (p["table"] == m["table"] and _same_pair(p, m)
                    and 0 <= m["t_start"] - p["t_end"] <= MERGE_GAP_S):
                cand = p
        if cand:
            cand["t_end"] = max(cand["t_end"], m["t_end"])
            for k in ("team_yellow", "team_blue", "yellow_city", "yellow_country",
                      "blue_city", "blue_country"):
                if m.get(k):
                    cand[k] = m[k]
        else:
            merged.append(dict(m))
    return merged


def _segment(samples):
    if not samples:
        return []
    tbl = _smooth_table(samples)
    segments, cur, last_t = [], None, None
    for s, table in zip(samples, tbl):
        if table is None:
            continue
        t = s["t"]
        same = cur is not None and cur["table"] == table and t - last_t <= MATCH_BRIDGE_S
        if not same:
            cur = {"table": table, "start": t, "end": t, "ys": [], "bs": [],
                   "tc": {}, "tk": {}, "countdown": None}
            segments.append(cur)
        cur["end"] = t
        # Tie city/country to the team NAME read on each side at this instant.
        if s["yellow"]:
            cur["ys"].append(s["yellow"])
            if s.get("city_y"): cur["tc"].setdefault(s["yellow"], []).append(s["city_y"])
            if s.get("country_y"): cur["tk"].setdefault(s["yellow"], []).append(s["country_y"])
        if s["blue"]:
            cur["bs"].append(s["blue"])
            if s.get("city_b"): cur["tc"].setdefault(s["blue"], []).append(s["city_b"])
            if s.get("country_b"): cur["tk"].setdefault(s["blue"], []).append(s["country_b"])
        if s["timer"] and cur["countdown"] is None:   # first running countdown
            cur["countdown"] = t
        last_t = t
    matches = []
    for seg in segments:
        yc, bc = _resolve_pair(seg["ys"], seg["bs"])
        ycity, ycountry = _loc_for(yc, seg["tc"], seg["tk"])
        bcity, bcountry = _loc_for(bc, seg["tc"], seg["tk"])
        # Start the clip 3s before the countdown starts (skip the presentation),
        # falling back to the banner start if no countdown was read.
        start = seg["countdown"] - PRE_ROLL_S if seg["countdown"] is not None else seg["start"]
        matches.append({"table": seg["table"],
                        "team_yellow": yc["rep"] if yc else None,
                        "team_blue": bc["rep"] if bc else None,
                        "yellow_city": ycity, "yellow_country": ycountry,
                        "blue_city": bcity, "blue_country": bcountry,
                        "t_start": round(max(0.0, start), 1),
                        "t_end": round(seg["end"], 1)})
    matches = _merge_fragments(matches)
    return [m for m in matches if m["t_end"] - m["t_start"] >= MATCH_MIN_S]


def _apply_roster(matches, roster):
    if not roster:
        return matches
    for m in matches:
        for k in ("team_yellow", "team_blue"):
            if m[k]:
                name, score = overlay.snap(m[k], roster)
                if score >= SNAP_MIN:
                    m[k] = name
    return matches


def parse_video(video, templates, cfg: OverlayConfig = overlay.DEFAULT,
                roster=None, ocr_fps=1.0, workers=0):
    """Parse a local video file into a list of matches (chronological)."""
    samples, fps, total = _sample(video, templates, cfg, ocr_fps, workers)
    matches = _segment(samples)
    matches = _apply_roster(matches, roster)
    return matches, round(total / fps, 1)
