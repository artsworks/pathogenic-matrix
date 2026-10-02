# Pathogenic Matrix

A live build advisor for [Pathogenic](https://store.steampowered.com/app/3808690/).
A small read-only Godot-ModLoader mod streams your run state to a local Python
app. The app shows your build and ranks every visible choice (3-pedestal
rewards, shop items, level-up mutations and evolutions) with a transparent
score, reasons, warnings and the game's own stat text.

```
Pathogenic + mod ──▶ matrix_state.json / POST ──▶ python app/run.py ──▶ browser tab (2nd monitor)
                 └─▶ matrix_logs/session_*.jsonl  (for calibration)
```

## Quick start (Windows)

1. Install Python 3.10+ (tick "Add to PATH").
2. Copy `dist/Artsworks-PathogenicMatrix-<version>.zip` into the game's `mods` folder.
3. Double-click `run.bat` (or run `python app\run.py --open`) and play.

Full walkthrough for first-time modders: [docs/03-install-windows.md](docs/03-install-windows.md).

## Status

M1–M3 of the plan: state inspector mod, live dashboard, explainable heuristic
recommender. The mod was written against the decompiled **demo** build and has
**not yet been confirmed on the release build**. The first real run plus its
session log is what confirms it.

## Layout

| Path | What |
|---|---|
| `mods/Artsworks-PathogenicMatrix/` | read-only observer mod that feeds the app (`observer.gd` does the work) |
| `mods/Artsworks-TowerDefense/` | gameplay mod, work in progress: hooks room and level generation |
| `mods/Artsworks-QoL/` | quality-of-life script extensions, work in progress |
| `app/run.py`, `app/matrix/` | stdlib HTTP/SSE server and recommender |
| `app/static/` | dashboard |
| `data/catalog.demo.json` | organelle/mutation catalog extracted from the demo |
| `tools/pack_mod.py` | builds one zip per mod into `dist/` |
| `tools/extract_catalog.py` | rebuilds the demo catalog from a GDRE-recovered project |
| `docs/` | investigation notes, architecture and log schema, install guide |

## Mods

Each folder under `mods/` is one Godot-ModLoader mod named `<Namespace>-<Name>`,
matching its `manifest.json`. It needs a `manifest.json` and a `mod_main.gd`;
`pack_mod.py` copies every other file in the folder into the zip as well. Only
PathogenicMatrix talks to the Python app. TowerDefense and QoL run entirely
inside the game.

## Development

```
python -m pip install ruff==0.6.9 mypy==1.11.2 gdtoolkit==4.3.3 "setuptools<70"
ruff check app tools tests && ruff format --check app tools tests && mypy
PYTHONPATH=app python -m unittest discover -s tests
gdparse $(find mods -name '*.gd') && gdlint $(find mods -name '*.gd') && gdformat --check $(find mods -name '*.gd')
python tools/pack_mod.py                             # every mod -> dist/<Namespace>-<Name>-<version>.zip
python tools/pack_mod.py --mod Artsworks-QoL         # one mod (repeat --mod for more)
python app/run.py --replay path/to/session_X.jsonl   # drive the dashboard without the game
```

## License

GPL-3.0 — see [LICENSE](LICENSE).

Note: `data/catalog.demo.json` contains item names and descriptions extracted
from the Pathogenic demo build. Those names, descriptions and all game assets
remain the property of the game's developer and are not covered by this license.
