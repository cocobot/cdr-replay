"""Read the broadcast overlay of a Coupe de France de Robotique stream.

The overlay uses the fixed *Ethnocentric* display font, which generic OCR
(Tesseract) reads poorly. We instead match each glyph against templates
rendered once from the font, which is reliable because the font is pixel
stable. Team names are optionally snapped to a known roster afterwards.

Everything that depends on the overlay layout lives in `OverlayConfig`, so a
different competition (e.g. junior) can be supported by passing different
regions/thresholds without touching the algorithm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Layout configuration (defaults calibrated on the senior 2025 stream, 1280x720)
# ---------------------------------------------------------------------------

@dataclass
class OverlayConfig:
    frame_size: tuple = (1280, 720)
    # team-name text bands (x1, y1, x2, y2). yellow = left, blue = right.
    team_yellow: tuple = (0, 595, 360, 614)
    team_blue: tuple = (920, 595, 1280, 614)
    team_thresh: int = 200
    # table pill "TABLE N"
    table_region: tuple = (575, 625, 700, 660)
    table_thresh: int = 180
    # match countdown "M:SS", centered under the table pill
    timer_region: tuple = (580, 668, 680, 703)
    timer_thresh: int = 170
    # city / country subtitle (classic font, under each team name) — Tesseract
    city_yellow: tuple = (8, 620, 360, 650)
    city_blue: tuple = (888, 620, 1268, 650)
    country_yellow: tuple = (8, 650, 360, 680)
    country_blue: tuple = (888, 650, 1268, 680)
    city_thresh: int = 205
    # banner-presence probe: flat desaturated grey bars behind the two names
    banner_regions: tuple = ((10, 596, 340, 648), (940, 596, 1270, 648))
    banner_min: float = 0.5
    # glyph matching
    scale: int = 4
    box: tuple = (44, 30)        # template canvas (h, w)
    aspect_w: float = 0.12       # weight of width/height penalty


DEFAULT = OverlayConfig()


# ---------------------------------------------------------------------------
# Glyph templates
# ---------------------------------------------------------------------------

def _norm_glyph(img, box):
    g = cv2.resize(img, (box[1], box[0]), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32) / 255.0


def build_templates_from_specimen(png_path, cfg: OverlayConfig = DEFAULT):
    """Extract A-Z and 0-9 templates from a dafont glyph-map image of the font.
    Lowercase glyphs are identical to uppercase in Ethnocentric, so caps suffice.
    Returns {char: {"img": float32[h,w], "aspect": float}}."""
    rows_map = {0: "ABCDEFGH", 1: "IJKLMNOP", 2: "QRSTUVW", 3: "XYZ",
                8: "01234567", 9: "89"}
    img = cv2.imread(png_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(png_path)
    binary = (img < 80).astype(np.uint8) * 255
    n, labels, stats, cent = cv2.connectedComponentsWithStats(binary, 8)
    comps = [(stats[i][0], stats[i][1], stats[i][2], stats[i][3], i, cent[i][1])
             for i in range(1, n) if stats[i][4] > 200 and stats[i][3] > 25]
    comps.sort(key=lambda c: c[5])
    rows, cur = [], []
    for c in comps:
        if cur and c[5] - cur[-1][5] > 40:
            rows.append(cur); cur = []
        cur.append(c)
    if cur:
        rows.append(cur)
    templates = {}
    for ri, chars in rows_map.items():
        row = sorted(rows[ri], key=lambda c: c[0])
        if len(row) != len(chars):
            raise ValueError(f"specimen row {ri}: expected {len(chars)} got {len(row)}")
        for (x, y, w, h, i, _), ch in zip(row, chars):
            glyph = (labels[y:y + h, x:x + w] == i).astype(np.uint8) * 255
            templates[ch] = {"img": _norm_glyph(glyph, cfg.box), "aspect": w / h}
    return templates


def save_templates(templates, npz_path):
    keys = sorted(templates)
    np.savez_compressed(
        npz_path,
        keys="".join(keys),
        imgs=np.stack([templates[k]["img"] for k in keys]),
        aspects=np.array([templates[k]["aspect"] for k in keys], dtype=np.float32),
    )


def load_templates(npz_path):
    d = np.load(npz_path)
    keys = str(d["keys"])
    return {k: {"img": d["imgs"][i], "aspect": float(d["aspects"][i])}
            for i, k in enumerate(keys)}


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------

def _preprocess(frame, region, thresh, cfg):
    x1, y1, x2, y2 = region
    crop = frame[y1:y2, x1:x2]
    big = cv2.resize(crop, (crop.shape[1] * cfg.scale, crop.shape[0] * cfg.scale),
                     interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
    return th


def _segment_glyphs(binary):
    """Glyphs (left->right) of the main text block; drop noise/video bleed."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    H = binary.shape[0]
    comps = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 0.35 * H <= h <= 1.05 * H and w >= 0.05 * H and area >= 0.015 * H * H:
            comps.append((x, y, w, h, i))
    if not comps:
        return []
    bottoms = [c[1] + c[3] for c in comps]
    medb = np.median(bottoms)
    comps = [c for c in comps if abs((c[1] + c[3]) - medb) <= 0.30 * H]
    comps.sort(key=lambda c: c[0])
    if not comps:
        return []
    mw = np.median([c[2] for c in comps])
    blocks, cur = [], [comps[0]]
    for prev, c in zip(comps, comps[1:]):
        if c[0] - (prev[0] + prev[2]) > 3.0 * mw:
            blocks.append(cur); cur = [c]
        else:
            cur.append(c)
    blocks.append(cur)
    block = max(blocks, key=lambda b: (len(b), sum(g[2] for g in b)))
    return [{"x": int(x), "w": int(w), "h": int(h),
             "img": (labels[y:y + h, x:x + w] == i).astype(np.uint8) * 255}
            for x, y, w, h, i in block]


def _best_match(glyph_img, templates, cfg, allowed=None):
    q = _norm_glyph(glyph_img, cfg.box)
    qa = glyph_img.shape[1] / glyph_img.shape[0]
    qn = np.linalg.norm(q) + 1e-6
    best_ch, best_s = "?", -1e9
    for ch, t in templates.items():
        if allowed is not None and ch not in allowed:
            continue
        ti = t["img"]
        cos = float(np.sum(q * ti) / (qn * (np.linalg.norm(ti) + 1e-6)))
        ap = abs(qa - t["aspect"]) / max(qa, t["aspect"])
        s = cos - cfg.aspect_w * ap
        if s > best_s:
            best_s, best_ch = s, ch
    return best_ch


def recognize(frame, region, thresh, templates, cfg=DEFAULT):
    glyphs = _segment_glyphs(_preprocess(frame, region, thresh, cfg))
    if not glyphs:
        return ""
    mw = np.median([g["w"] for g in glyphs])
    out, prev_r = [], None
    for g in glyphs:
        if prev_r is not None and (g["x"] - prev_r) > 0.55 * mw:
            out.append(" ")
        out.append(_best_match(g["img"], templates, cfg))
        prev_r = g["x"] + g["w"]
    return "".join(out).strip()


def read_team(frame, side, templates, cfg=DEFAULT):
    region = cfg.team_yellow if side == "yellow" else cfg.team_blue
    return recognize(frame, region, cfg.team_thresh, templates, cfg).strip() or None


def read_timer(frame, templates, cfg=DEFAULT):
    """Countdown M:SS via digit templates (colon dots fall below the glyph filter)."""
    digit_t = {k: v for k, v in templates.items() if k.isdigit()}
    glyphs = _segment_glyphs(_preprocess(frame, cfg.timer_region, cfg.timer_thresh, cfg))
    digits = [_best_match(g["img"], digit_t, cfg) for g in glyphs]
    if len(digits) < 3:
        return None
    d = "".join(digits)[-3:]
    return f"{d[0]}:{d[1:]}"


# Countries seen at the Coupe de France de Robotique / Eurobot (French names).
COUNTRIES = ["France", "Belgique", "Suisse", "Allemagne", "Tunisie", "Maroc",
             "Espagne", "Italie", "Mexique", "Pologne", "Tchéquie", "Slovénie",
             "Roumanie", "Pays-Bas", "Royaume-Uni", "Portugal", "Brésil", "Colombie"]


def _ocr_line(frame, region, thresh, otsu=False):
    import pytesseract
    x1, y1, x2, y2 = region
    crop = frame[y1:y2, x1:x2]
    big = cv2.resize(crop, (crop.shape[1] * 4, crop.shape[0] * 4), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    flag = cv2.THRESH_BINARY + (cv2.THRESH_OTSU if otsu else 0)
    _, th = cv2.threshold(gray, 0 if otsu else thresh, 255, flag)
    return pytesseract.image_to_string(th, config="--psm 7").strip()


def read_city(frame, side, cfg=DEFAULT):
    """City under a team name (white text on the banner). Tesseract — classic font."""
    region = cfg.city_yellow if side == "yellow" else cfg.city_blue
    t = re.sub(r"[^0-9A-Za-zÀ-ÿ' .-]", "", _ocr_line(frame, region, cfg.city_thresh))
    t = re.sub(r"\s+", " ", t).strip(" .-'")
    return t or None


def read_country_raw(frame, side, cfg=DEFAULT):
    """Raw country read (low-contrast grey text). Snap+vote done by the caller."""
    region = cfg.country_yellow if side == "yellow" else cfg.country_blue
    raw = _ocr_line(frame, region, 0, otsu=True) or _ocr_line(frame, region, cfg.city_thresh)
    return re.sub(r"[^A-Za-zÀ-ÿ-]", "", raw).strip() or None


def snap_country(raw):
    """Snap a noisy country read to the known list (handles dropped first letter)."""
    if not raw:
        return None
    q = _normalize(raw)
    best, bs = None, 0.0
    for c in COUNTRIES:
        r = SequenceMatcher(None, q, _normalize(c)).ratio()
        if r > bs:
            bs, best = r, c
    return best if bs >= 0.55 else None


def read_table(frame, cfg=DEFAULT):
    """Table number via the digit templates over the 'TABLE N' pill."""
    # Tesseract is avoided; we template-match digits in the pill's right half.
    import pytesseract  # optional dependency, only used here
    x1, y1, x2, y2 = cfg.table_region
    crop = frame[y1:y2, x1:x2]
    big = cv2.resize(crop, (crop.shape[1] * 3, crop.shape[0] * 3),
                     interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, cfg.table_thresh, 255, cv2.THRESH_BINARY)
    text = pytesseract.image_to_string(th, config="--psm 7").strip()
    m = re.search(r"(\d+)", text)
    return m.group(1) if m else None


def banner_present(frame, cfg=DEFAULT):
    """True iff the team-name banner bars are displayed (a real match shot)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    S, V = hsv[:, :, 1], hsv[:, :, 2]
    for x1, y1, x2, y2 in cfg.banner_regions:
        s, v = S[y1:y2, x1:x2], V[y1:y2, x1:x2]
        if ((s < 45) & (v > 95) & (v < 205)).mean() < cfg.banner_min:
            return False
    return True


# ---------------------------------------------------------------------------
# Roster snapping (optional)
# ---------------------------------------------------------------------------

def _normalize(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c if c.isalnum() else " " for c in s.upper())
    return " ".join(s.split())


def load_roster(path):
    return [(t.strip(), _normalize(t)) for t in open(path, encoding="utf-8") if t.strip()]


def snap(raw, roster):
    """Snap a raw OCR read to the closest roster name. Returns (name, score)."""
    q = _normalize(raw or "")
    if not q or not roster:
        return raw, 0.0
    best, bs = raw, 0.0
    for orig, nt in roster:
        r = SequenceMatcher(None, q, nt).ratio()
        if r > bs:
            bs, best = r, orig
    return best, round(bs, 2)
