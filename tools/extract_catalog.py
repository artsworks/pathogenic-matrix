#!/usr/bin/env python3
"""Extract Pathogenic item/mutation catalog from a GDRE-recovered project.

Usage: python3 tools/extract_catalog.py <recovered_dir> <out.json>

Parses BodypartResource .tres files, exported properties from the matching
.tscn scene root node, Mutation/Evolution resources, and translations.csv
(English column) to produce a flat catalog the webapp can consume.
"""

import csv
import json
import re
import sys
from pathlib import Path

BODYPART_TAGS = {
    0: "EnergyGenerator",
    1: "EnergyConsumer",
    2: "Weapon",
    3: "AttackModifier",
    4: "CanBeAttackModified",
    5: "Lash",
    6: "Internal",
    7: "External",
    8: "Any",
    9: "Active",
    10: "CanBeBulletModified",
    11: "BulletModifier",
    12: "UsesBulletWeapons",
    13: "ShootsBullets",
    14: "Upgrade",
    15: "WeaponModifier",
    16: "UsesWeapons",
    17: "MeleeWeapon",
    18: "UsesMeleeWeapons",
}

# Scene-root exported props worth capturing for the catalog.
SCENE_PROPS = [
    "stats_text",
    "stats_after_text",
    "charged_text",
    "chainable_text",
    "max_energy",
    "attack_speed",
    "stamina_cost",
    "attack_speed_charge_bonus",
    "spread_deg",
    "damage",
    "base_damage",
    "num_bullets",
    "pierce",
    "bounce",
    "shot_recoil",
    "lifetime",
    "range",
    "speed",
    "heal_amount",
    "generate_charge_progress",
]

RE_TRES_PROP = re.compile(r"^(\w+)\s*=\s*(.+)$")
RE_TAG_ARR = re.compile(r"\[([0-9,\s]*)\]")
RE_NODE_BLOCK = re.compile(r"^\[node ")


def parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith('"'):
        return raw.strip('"')
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [parse_value(x) for x in inner.split(",") if x.strip()] if inner else []
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            pass
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith("Color"):
        m = re.findall(r"[\d.]+", raw)
        return [float(x) for x in m[:4]] if m else raw
    if raw.startswith(("ExtResource", "SubResource", "Resource")):
        return {"ref": raw}
    if raw.startswith(("Vector", "NodePath", "PackedStringArray")):
        return raw
    return raw


def parse_tres(path: Path) -> dict:
    out = {}
    in_resource = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("[resource]"):
            in_resource = True
            continue
        if line.startswith("["):
            in_resource = False
        if not in_resource:
            continue
        m = RE_TRES_PROP.match(line)
        if m:
            out[m.group(1)] = parse_value(m.group(2))
    return out


def parse_scene_root_props(path: Path) -> dict:
    """Exported props on the root node of the .tscn (the bodypart instance)."""
    out = {}
    seen_first_node = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if RE_NODE_BLOCK.match(line):
            if seen_first_node:
                break
            seen_first_node = True
            continue
        if not seen_first_node:
            continue
        m = RE_TRES_PROP.match(line.strip())
        if m and m.group(1) in SCENE_PROPS:
            out[m.group(1)] = parse_value(m.group(2))
    return out


def load_translations(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0] and row[0] != "key":
                out[row[0]] = row[1]
    return out


def tag_names(tags) -> list:
    if not isinstance(tags, list):
        return []
    return [BODYPART_TAGS.get(t, f"tag_{t}") for t in tags]


def main():
    root = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    tr = load_translations(root / "translations" / "translations.csv")

    bodyparts = []
    bp_dir = root / "scn" / "player" / "bodyparts"
    for tres in sorted(bp_dir.rglob("*.tres")):
        if tres.name in ("all_bodyparts.tres",):
            continue
        d = parse_tres(tres)
        if "ui_name" not in d and "tags" not in d:
            continue  # not a BodypartResource (e.g. connection textures)
        scn = tres.with_suffix(".tscn")
        props = parse_scene_root_props(scn) if scn.exists() else {}
        for k in ("stats_text", "stats_after_text", "charged_text", "chainable_text"):
            if isinstance(props.get(k), str):
                props[k] = tr.get(props[k], props[k])
        script_gd = tres.with_suffix(".gd")
        bodyparts.append(
            {
                "id": tres.stem,
                "kind": tres.parent.name,  # external | internal | other
                "name_key": d.get("ui_name"),
                "name": tr.get(d.get("ui_name", ""), d.get("ui_name")),
                "desc_key": d.get("description"),
                "description": tr.get(d.get("description", ""), d.get("description")),
                "flavor": tr.get(d.get("flavor_text", ""), "") if d.get("flavor_text") else "",
                "tags": tag_names(d.get("tags")),
                "random_weight": d.get("random_weight", 1.0),
                "needs_connection_warning": tag_names(d.get("needs_connection_warning")),
                "disabled": d.get("disabled", False),
                "stats": props,
                "script": str(script_gd.relative_to(root)) if script_gd.exists() else None,
            }
        )

    mutations = []
    for base, kind in [
        (root / "scn" / "player" / "mutations" / "all", "mutation"),
        (root / "scn" / "player" / "evolutions", "evolution"),
    ]:
        if not base.exists():
            continue
        for tres in sorted(base.glob("*.tres")):
            if tres.name in ("all_mutations.tres", "empty_mutation.tres"):
                continue
            d = parse_tres(tres)
            if "ui_name" not in d:
                continue
            mutations.append(
                {
                    "id": tres.stem,
                    "kind": kind,
                    "name_key": d.get("ui_name"),
                    "name": tr.get(d.get("ui_name", ""), d.get("ui_name")),
                    "desc_key": d.get("description"),
                    "description": tr.get(d.get("description", ""), d.get("description")),
                    "random_weight": d.get("random_weight", 1.0),
                    "reward_drop_rate": d.get("reward_drop_rate", 0.0),
                    "bonus_damage": d.get("bonus_damage"),
                    "bonus_hp": d.get("bonus_hp"),
                }
            )

    catalog = {
        "source": "GDRE recovery",
        "bodypart_tags": {v: k for k, v in BODYPART_TAGS.items()},
        "bodyparts": bodyparts,
        "mutations": mutations,
    }
    out_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False))
    print(f"bodyparts={len(bodyparts)} mutations/evolutions={len(mutations)} -> {out_path}")


if __name__ == "__main__":
    main()
