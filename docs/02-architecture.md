# Architecture

```
Pathogenic (Godot 4 + Godot-ModLoader)
  └── mods-unpacked/Artsworks-PathogenicMatrix/observer.gd   (read-only)
        │  watches SignalBus events + checks a few G.* values every 0.25 s
        ├── user://matrix_state.json         latest snapshot (atomic rename)
        ├── POST http://127.0.0.1:48710/state (optional, lower latency)
        ├── user://matrix_catalog.json       live organelle/mutation catalog
        └── user://matrix_logs/session_<unix>.jsonl   event log, one per launch
                     │
                     ▼
app/ (Python 3.10+, stdlib only)
  - FileWatcher: polls matrix_state.json / matrix_catalog.json every 0.2 s
  - POST /state ingest
  - recommend.py: scores every choice group → reasons[] / warnings[] / raw option
  - user://matrix_logs/recommend_<unix>.jsonl  what the app recommended, per choice_id
  - GET /state, GET /recommend, SSE /events, static dashboard
                     │
                     ▼
Browser tab (second monitor): ranked summary up top, expandable details per pick
```

## Latency budget (~1 s goal)

"Within ~1 s" = from the choice appearing in game to the dashboard showing it.

| Step | Worst case |
|---|---|
| Mod notices the change (fingerprint check every 0.25 s, or a SignalBus event) | 0.25 s |
| File write → app poll (0.2 s), or HTTP POST (immediate) | 0.2 s |
| Scoring + SSE push | < 10 ms |

Worst case is about 0.5 s over the file path, and faster over HTTP.

## Why file-first plus optional POST

`user://` writes always work and don't need the app to be running. The POST is
faster but only works while the app is up. The app reads the file on start, so
it doesn't matter whether you start the app or the game first.

## Mod performance

- Nothing is serialised unless something changed. The cheap per-tick check is:
  level, reward-node count, level-up open, player level/money/max HP/mutation
  count/death, and current room. A full snapshot is also sent every 2 s as a
  heartbeat so HP and stamina stay fresh.
- Rewards come from the game's own `bodypart_reward` node group. Shop items are
  found by walking only `G.current_room`, not the whole scene tree.
- Tooltip text is cached per node/resource, and the cache is cleared each level.

## Mod config (optional)

`user://matrix_config.json`:

```json
{ "http_enabled": true, "http_url": "http://127.0.0.1:48710/state",
  "file_enabled": true, "log_enabled": true, "poll_interval": 0.25, "max_log_files": 30 }
```

## State schema (v2)

```jsonc
{
  "schema": 2, "ts": 1790000000.0, "session": "1790000000", "mod_version": "0.1.0",
  "in_run": true, "level_number": 2, "rng_seed": "12345", "parasite": "GREEN",
  "shopkeeper_angered": false, "room": { "name": "Shop1", "type": "Shop" },
  "player": {
    "hp": 6, "max_hp": 10, "armor": 0, "level": 3, "dna": 4, "dna_to_level_up": 12,
    "money": 40, "stamina": 50, "max_stamina": 100, "speed": 1.0, "player_damage_mult": 1.0,
    "dodge_cd": 1.0, "dodge_invulnerability": 0.3, "pickup_range_mult": 1.0, "dead": false,
    "slots": [ { "slot": "Ext1", "internal": false, "connects_to": ["Int1"],
                 "bodypart": { "id": "assault_rifle", "name": "Pulsar Gland", "rarity": "Common",
                               "tags": ["..."], "energy": 1.0, "max_energy": 3, "charge": 0.5,
                               "tooltip": "<game tooltip BBCode>" } } ],
    "mutations": [ { "type": "mutation", "id": "...", "key": "...", "name": "...", "description": "...", "tooltip": "..." } ]
  },
  "choices": [
    { "choice_id": "reward:choice3:123", "kind": "reward", "exclusive": true, "options": [ /* option */ ] },
    { "choice_id": "shop:456:2",         "kind": "shop",   "exclusive": false, "options": [ /* option + cost */ ] },
    { "choice_id": "level_up:<seed>:3",  "kind": "level_up", "exclusive": true, "options": [ /* option */ ] }
  ]
}
```

An option looks like this:
`{type: bodypart|mutation|evolution|pickup|unknown, id, key, name, description, tooltip, tags, rarity | rarity_range, needs_connection, cost, pay_with_blood, bonus_damage, bonus_hp, is_health}`.
`key` is unique within its choice group and appears in both logs.

## Session log (`session_<unix>.jsonl`)

One JSON object per line. Every line has `ev`, `ts` and `session`.

| `ev` | Extra fields |
|---|---|
| `session_start` | mod_version, schema, game_version, engine, os, locale |
| `catalog` | full live catalog (so a zipped log is self-contained) |
| `signal_missing` / `signal_arity_changed` | a SignalBus signal that differs from the demo |
| `player_created` | parasite, rng_seed, level_number |
| `level_started` | level_number |
| `room_started` / `room_finished` | room, level_number; finished adds duration_s, hp_start/end, hits_taken, damage_taken, kills |
| `choice_presented` | choice_id, kind, exclusive, options, full `state` snapshot |
| `choice_taken` | choice_id, kind, taken (option key); shop adds cost/pay_with_blood; level-up adds added_mutations |
| `bodypart_attached` | id, rarity, slot |
| `boss_beaten` | level_number, room |
| `run_end` | cause, level_number, room, state |
| `session_end` | — |

To see where you disagreed with the app, join `choice_presented` / `choice_taken`
(mod log) with `recommendation` (app log) on `session` + `choice_id`.
`python app/run.py --replay session_X.jsonl` replays a session into the
dashboard without the game.
