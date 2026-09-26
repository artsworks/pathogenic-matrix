# Pathogenic internals — investigation report

Source: `Pathogenic Demo v4` (itch.io, Jan 2026 build), PCK fully recovered with
GDRE Tools 2.6.4 — 441 GDScripts decompiled, 412 resources, full scene/resource
tree and `translations.csv` recovered. The release build (Steam, Godot
4.7/4.8-era) additionally ships the Godot-ModLoader — the demo predates it —
but the gameplay classes below are the same codebase the modding layer exposes.

## ModLoader surface (release build)

The game uses **Godot-ModLoader** (GodotModding org), the standard framework —
the log lines "Installed all script extensions" / "Applied all scene
extensions" are its signatures, and Workshop mods are `.zip` packages with:

```
MyMod.zip
├── manifest.json                     # Thunderstore-style manifest (copy)
└── mods-unpacked/<Namespace>-<Name>/ # mod code, addressed as res://mods-unpacked/<Namespace>-<Name>/...
    ├── manifest.json                 # the copy Godot-ModLoader reads
    ├── mod_main.gd                   # extends Node, _init() is the entrypoint
    └── ...
```

Loader APIs available to mods (autoload-style globals):

- `ModLoaderMod.install_script_extension(path)` — wrap/replace a game script
- `ModLoaderMod.install_script_hooks(res_path, ext_path)` — method hooks
- `ModLoaderMod.get_unpacked_dir()` → `res://mods-unpacked`
- `ModLoaderLog.info(msg, mod_name)`
- All game `class_name` types and autoloads resolve inside mod scripts.

**Key finding for this project: no script hooks are needed at all for the
inspector.** Game state is reachable through autoloads, and every interesting
event is already on `SignalBus`.

## Autoloads (the whole game state API)

From `project.godot`:

| Autoload | Script | Holds |
|---|---|---|
| `G` | `scn/globals.gd` | `player`, `editor`, `ui`, `level_generator`, `game_state`, `current_room`, `level_number`, `rng_seed`, `selected_parasite`, `bodyparts`, `mutations`, `bodyparts_with_tag`, `rooms_with_type` |
| `SignalBus` | `scn/signal_bus.gd` | every game event (below) |
| `SaveManager` | `scn/save_manager.gd` | settings |
| `PlasmidManager` | `scn/metaprogression/plasmids/plasmid_manager.gd` | meta upgrades |
| `AntibioticsManager` | `scn/metaprogression/antibiotics/antibiotics_manager.gd` | difficulty modifiers |
| `AudioManager` | `scn/audio_manager.tscn` | sounds |

### SignalBus events worth subscribing to

`bodypart_reward_spawned(Bodypart)`, `bodypart_attached(Bodypart)`,
`bodypart_detached(Bodypart)`, `mutation_chosen`, `pick_up_taken(Pickup)`,
`room_entered/room_started/room_finished/room_entered_first_time(Room)`,
`player_created(Player)`, `player_hit(float)`, `player_dodged`,
`next_level_started`, `level_ready`, `shopkeeper_angered`, `boss_beaten`,
`parasite_selected`, `player_modify_tick`, `gun_modify_tick`, `bullet_fired`.

## The build model

- `G.player: Player` (extends `Cell`) — `hp`, `max_hp`, `armor`, `level`,
  `dna`, `money`, `stamina`/`max_stamina`, `speed`, `base_speed`,
  `player_damage_mult`, `pickup_range_mult`, `dodge_cd`,
  `dodge_invulnerability`, `mutations: Array`, `slots: Array[Slot]`.
  `dna_to_level_up() = 10 + level*3`.
- `Slot` — `internal` (bool), `bodypart`, `connections: Dictionary[Slot,Connection]`,
  `connect_to`, `mirror_slot` (paired body symmetry), `can_accept_bodypart`
  (internal slots take Internal-tagged parts, external take External).
- `Bodypart` — `res: BodypartResource`, `rarity` (Common/Rare/Epic/Legendary),
  `energy`/`max_energy`/`charge`, `connections` = adjacent slots' parts.
  `can_connect_to(b)` implements the synergy graph:
  EnergyGenerator→EnergyConsumer, WeaponModifier→Weapon,
  AttackModifier→Weapon|CanBeAttackModified, BulletModifier→CanBeBulletModified,
  ShootsBullets→UsesBulletWeapons, Weapon→UsesWeapons, MeleeWeapon→UsesMeleeWeapons.
  `can_combine_with`: same `res` → merges to next rarity (cap Legendary);
  `Upgrade`-tagged parts bump any part's rarity.
- `BodypartResource` (.tres catalog entries) — `ui_name`, `description`,
  `flavor_text` (all translation keys), `tags`, `needs_connection_warning`,
  `random_weight`, `disabled`. Scene = same path with `.tscn`.
- Stat scaling by rarity is per-part, e.g. `damage_mult: 0.25 + rarity*0.15`,
  `heal`, `range_extender: 1.5 + rarity*0.25` — linear, defined in each `.gd`.
- Mutations apply once via `Mutation.apply()` — typically connect to SignalBus
  and mutate attacks/stats (e.g. `damage_mutation`: `attack.damage += base_damage*0.1`).
- `Evolution` (extends Mutation) — at player level 2 and 5 the 4 mutation
  picks are replaced by 3 evolution choices + `skip_evolution`. Evolutions
  swap the player scene and carry bodyparts over to matching slot names;
  optional `bonus_damage`/`bonus_hp`.

## Choices (what the tool recommends on)

1. **Reward / "3-choice" pedestals** — `BodypartReward` nodes
   (`scn/environ/pickups/bodypart_reward*.gd`). `pick_bodypart()` draws from
   `item_pool` or `G.bodyparts_with_tag[item_type]` plus mutations with
   `reward_drop_rate > 0`; weighted by `random_weight`; `choose_one` +
   `unique_from` mark mutually-exclusive choices; `rarity_from/to` roll rarity.
   Item rooms are placed per level (`level_generator.gd`, RoomType.Item/Shop).
2. **Shop** — `scn/environ/rooms/special/shop.gd` + `ShopItem` nodes
   (`scn/environ/pickups/shop_item.gd`, *no class_name* — detect by script path
   or `has_method("clear_price")`). Price = `cost × ((level−1)/4 + 1) ×
   randf(1.0..1.3)`, 1-in-6 chance of half price. `pay_with_blood` = devil shop
   (cost subtracts `max_hp` instead of money). Angering the shopkeeper
   (`G.game_state.is_shopkeeper_angered`, `ShopRerollMachine`) turns the shop
   hostile; `steal` mode after.
3. **Level-up mutations** — `G.editor.is_choosing_mutation()` +
   `G.editor.mutations` (4 picks, weighted from `G.mutations`, seeded
   `hash(G.rng_seed + "mut" + str(level))`).

## Static data catalog

`tools/extract_catalog.py` turns the recovered project into
`data/catalog.demo.json`: 88 organelles (32 external / 55 internal / 1 other)
and 44 mutations+evolutions with English names, descriptions, tags, weights,
and exported stats (attack_speed, stamina_cost, stats_text, etc.).

Names like "Secretor" = `gun.tres`, "Entrant Mitochondrion" = `generator.tres`.

## Caveats: demo vs release

- Demo has 3 playable pathogens (GREEN, STRAFER, WORM); release has 7 —
  `G.ParasiteType` enum is longer in the release. The mod resolves names via
  the enum at runtime, so it self-adjusts.
- The demo PCK predates the ModLoader; release script paths *may* have moved.
  The inspector duck-types ShopItem and uses `class_name` types + SignalBus
  (stable public-ish surface), and additionally self-dumps the live catalog
  (`matrix_catalog.json`) so the app can reconcile differences automatically.
