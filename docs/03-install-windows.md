# Install and first run (Windows, no modding experience needed)

This takes about 10 minutes the first time. Nothing here changes your save
files or game data: the mod only reads game state and writes its own files.

## 0. Before anything else: send the startup log (Step 0)

1. Launch Pathogenic once from Steam, go to the title screen, then quit.
2. Press `Win + R`, paste `%APPDATA%\Godot\app_userdata\Pathogenic\logs`, press Enter.
3. Zip everything in that folder (probably `godot.log` and maybe `modloader.log`) and send it over.
   If the folder doesn't exist, try `%APPDATA%\Pathogenic\logs` instead.
4. If the game has a Mods menu (on the title or options screen), send a screenshot of it too.

This tells us the ModLoader version, where the game looks for mods, and the
game version, so the mod's `manifest.json` matches your build.

## 1. Install Python (one time)

1. Download Python 3.12 or newer from https://www.python.org/downloads/windows/.
2. When the installer opens, tick **Add python.exe to PATH**, then click Install Now.
3. Check it worked: open a new Command Prompt and run `python --version`.

No other packages are needed.

## 2. Get Pathogenic Matrix

Download the repo as a zip from GitHub (green **Code** button → Download ZIP)
and unzip it somewhere, e.g. `C:\Tools\pathogenic-matrix`.

The mod zip is `dist\Artsworks-PathogenicMatrix-<version>.zip`. It's attached to
each release, or you can build it with `python tools\pack_mod.py`.

## 3. Install the mod

Godot-ModLoader loads zips from a `mods` folder next to the game executable:

1. In Steam, right-click Pathogenic → Manage → **Browse local files**.
2. Create a folder called `mods` there if it doesn't already exist.
3. Copy `Artsworks-PathogenicMatrix-<version>.zip` into `mods` (don't unzip it).
4. Start the game. If there's a Mods menu, make sure **PathogenicMatrix** is enabled.

> The exact folder is confirmed from your Step 0 log. If the startup log names
> a different mods path, use that one.

To check it loaded, look for lines containing `Artsworks-PathogenicMatrix` in
the log from Step 0, and for new files in
`%APPDATA%\Godot\app_userdata\Pathogenic\`:
`matrix_state.json`, `matrix_catalog.json` and a `matrix_logs` folder.

## 4. Run the companion app

Double-click `run.bat` in the unzipped folder. Or open a Command Prompt there and run:

```
python app\run.py --open
```

A browser tab opens at http://localhost:48710. Drag it to your second monitor.
You can start the app before or after the game. Close it with `Ctrl + C`.

If Windows Firewall asks, you can click Cancel: the app only listens on
`127.0.0.1` (your own PC).

## 5. What to check on your first run

- Start a run: Vitals and Build fill in within about a second.
- Walk into a 3-pedestal reward room: a **Pick one** group shows up, ranked,
  with a reason under each pick. Click a pick to see its full stats and the
  game's own tooltip.
- Open a shop: the **Shop** group ranks items by value per cost and warns about
  things you can't afford or that cost max HP.
- Level up: a **Level-up** group lists the 4 mutation picks (at levels 2 and 5,
  3 evolutions + skip).

## 6. Sending logs back for calibration

After a session, zip the whole
`%APPDATA%\Godot\app_userdata\Pathogenic\matrix_logs` folder and send it over.
It contains:

- `session_*.jsonl` from the mod: what was offered, what you took, how each room went.
- `recommend_*.jsonl` from the app: what it recommended for each choice.

The logs hold game data only (items, stats, rooms, a timestamp, your OS name and
game language). There are no account names, Steam IDs or file paths. The mod
keeps the newest 30 session files.

## Troubleshooting

| Symptom | Check |
|---|---|
| No `matrix_state.json` | Is the mod enabled? Does the game log show `Artsworks-PathogenicMatrix` lines? Is the zip in the right `mods` folder? |
| Dashboard says "offline" | Is the app still running in the Command Prompt? |
| Dashboard says "Not in a run" | Start a run. The state only fills in once a player exists. |
| Header says "demo catalog" | The live catalog hasn't been written yet (it happens once per launch, after the game loads its item list). |
| State lives somewhere else | `python app\run.py --user-dir "C:\path\to\folder"` |
| Port 48710 is in use | `python app\run.py --port 48720`, and set `http_url` in `matrix_config.json` to match. |
