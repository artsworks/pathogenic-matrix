"""Package the mod as a Godot-ModLoader zip.

Layout inside the zip:
    manifest.json                      (Thunderstore/Workshop-style copy)
    mods-unpacked/Artsworks-PathogenicMatrix/{manifest.json,mod_main.gd,observer.gd}

Usage: python tools/pack_mod.py [out.zip]
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD_ID = "Artsworks-PathogenicMatrix"
MOD_SRC = ROOT / "mod" / MOD_ID
FILES = ("manifest.json", "mod_main.gd", "observer.gd")


def pack(out: Path) -> Path:
    manifest = json.loads((MOD_SRC / "manifest.json").read_text(encoding="utf-8"))
    expected = f"{manifest['namespace']}-{manifest['name']}"
    if expected != MOD_ID:
        raise SystemExit(f"manifest namespace-name {expected!r} must match folder {MOD_ID!r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(MOD_SRC / "manifest.json", "manifest.json")
        for name in FILES:
            zf.write(MOD_SRC / name, f"mods-unpacked/{MOD_ID}/{name}")
    return out


def main(argv: list[str]) -> int:
    version = json.loads((MOD_SRC / "manifest.json").read_text(encoding="utf-8"))["version_number"]
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "dist" / f"{MOD_ID}-{version}.zip"
    print(f"Wrote {pack(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
