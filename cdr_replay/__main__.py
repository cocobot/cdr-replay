"""CLI: build the site data, or (re)generate glyph templates from a font specimen.

  python -m cdr_replay build [--config config/videos.yaml] [--ocr-fps 1] [--workers 0]
  python -m cdr_replay templates <specimen.png>
"""

import argparse
import sys
from pathlib import Path

from . import build as build_mod
from . import overlay


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cdr_replay")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="parse videos in config and write site/data")
    b.add_argument("--config", default="config/videos.yaml")
    b.add_argument("--ocr-fps", type=float, default=1.0)
    b.add_argument("--workers", type=int, default=0)
    b.add_argument("--cleanup", action="store_true", help="delete each video after parsing")

    t = sub.add_parser("templates", help="build glyph templates from a font specimen")
    t.add_argument("specimen", help="dafont glyph-map PNG of the Ethnocentric font")

    args = ap.parse_args(argv)
    if args.cmd == "build":
        build_mod.build(args.config, ocr_fps=args.ocr_fps, workers=args.workers, cleanup=args.cleanup)
    elif args.cmd == "templates":
        out = Path(__file__).resolve().parent / "data" / "templates.npz"
        out.parent.mkdir(parents=True, exist_ok=True)
        tpl = overlay.build_templates_from_specimen(args.specimen)
        overlay.save_templates(tpl, out)
        print(f"Wrote {out}: {''.join(sorted(tpl))}")


if __name__ == "__main__":
    main(sys.argv[1:])
