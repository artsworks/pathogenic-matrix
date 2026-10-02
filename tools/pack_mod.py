"""Package each mod under mods/ as a Godot-ModLoader zip.

Layout inside each zip:
    manifest.json                       (Thunderstore/Workshop-style copy)
    mods-unpacked/<Namespace>-<Name>/   (every file in mods/<Namespace>-<Name>/)

Usage: python tools/pack_mod.py [--mod <Namespace>-<Name> ...] [--out-dir dist]
Without --mod, every subdirectory of mods/ is packed.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODS_DIR = ROOT / "mods"
REQUIRED = ("manifest.json", "mod_main.gd")


def discover() -> list[str]:
    return sorted(p.name for p in MODS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def mod_files(src: Path) -> list[Path]:
    return sorted(
        p for p in src.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(src).parts)
    )


def pack(mod_id: str, out_dir: Path) -> Path:
    src = MODS_DIR / mod_id
    if not src.is_dir():
        raise SystemExit(f"no such mod: {src}")
    missing = [name for name in REQUIRED if not (src / name).is_file()]
    if missing:
        raise SystemExit(f"{mod_id}: missing {', '.join(missing)}")
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    expected = f"{manifest['namespace']}-{manifest['name']}"
    if expected != mod_id:
        raise SystemExit(f"manifest namespace-name {expected!r} must match folder {mod_id!r}")
    out = out_dir / f"{mod_id}-{manifest['version_number']}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src / "manifest.json", "manifest.json")
        for path in mod_files(src):
            zf.write(path, f"mods-unpacked/{mod_id}/{path.relative_to(src).as_posix()}")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build one release zip per mod in mods/.")
    parser.add_argument("--mod", action="append", dest="mods", metavar="ID", help="mod folder name; repeatable")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist", help="output directory (default: dist/)")
    args = parser.parse_args(argv)
    for mod_id in args.mods or discover():
        print(f"Wrote {pack(mod_id, args.out_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
