"""Explainable scoring for Pathogenic reward, shop and level-up choices.

v1 is a transparent heuristic over the game's BodypartTags and the live build.
Every pick carries the score, the reasons behind it and any warnings, plus the
raw option (including the game's own tooltip text) so the player can overrule it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

JSON = dict[str, Any]

RARITY_IDX = {"Common": 0, "Rare": 1, "Epic": 2, "Legendary": 3}
WEAPON_TAGS = {"Weapon", "ShootsBullets", "MeleeWeapon", "Lash"}
DEFENSIVE_NAME = re.compile(r"heal|armor|shield|life|defen|guard", re.I)


@dataclass
class Scored:
    key: str
    label: str
    score: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score_per_cost: float | None = None
    option: JSON = field(default_factory=dict)

    def to_json(self) -> JSON:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score, 2),
            "score_per_cost": None if self.score_per_cost is None else round(self.score_per_cost, 3),
            "reasons": self.reasons,
            "warnings": self.warnings,
            "option": self.option,
        }


@dataclass
class BuildProfile:
    equipped: list[JSON] = field(default_factory=list)
    weapons: int = 0
    bullet_mods: int = 0
    attack_mods: int = 0
    weapon_mods: int = 0
    generators: int = 0
    consumers: int = 0
    actives: int = 0
    equipped_ids: dict[str, int] = field(default_factory=dict)

    @property
    def modifiers(self) -> int:
        return self.bullet_mods + self.attack_mods + self.weapon_mods


class Catalog:
    def __init__(self, data: JSON | None = None) -> None:
        data = data or {}
        self.source: str = data.get("source", "none")
        self.bodyparts: dict[str, JSON] = {b["id"]: b for b in data.get("bodyparts", []) if "id" in b}
        self.mutations: dict[str, JSON] = {m["id"]: m for m in data.get("mutations", []) if "id" in m}

    def tags(self, bodypart_id: str) -> list[str]:
        return list(self.bodyparts.get(bodypart_id, {}).get("tags", []))

    def to_json(self) -> JSON:
        return {
            "source": self.source,
            "bodyparts": list(self.bodyparts.values()),
            "mutations": list(self.mutations.values()),
        }


def merge_catalogs(demo: JSON | None, live: JSON | None) -> Catalog:
    """Live entries win; demo fills gaps (e.g. stats the live dump lacks)."""
    if not live:
        return Catalog({**(demo or {}), "source": "demo" if demo else "none"})
    merged: JSON = {"source": "live", "bodyparts": [], "mutations": []}
    for kind in ("bodyparts", "mutations"):
        by_id = {e["id"]: dict(e) for e in (demo or {}).get(kind, []) if "id" in e}
        live_ids = set()
        for e in live.get(kind, []):
            if "id" not in e:
                continue
            live_ids.add(e["id"])
            by_id[e["id"]] = {**by_id.get(e["id"], {}), **e}
        merged[kind] = [v for k, v in by_id.items() if k in live_ids]
    return Catalog(merged)


def _slot_tags(slot: JSON, catalog: Catalog) -> list[str]:
    b = slot.get("bodypart") or {}
    return list(b.get("tags") or catalog.tags(b.get("id", "")))


def build_profile(state: JSON, catalog: Catalog) -> BuildProfile:
    prof = BuildProfile()
    for slot in (state.get("player") or {}).get("slots", []):
        b = slot.get("bodypart")
        if not b:
            continue
        tags = set(_slot_tags(slot, catalog))
        prof.equipped.append({**b, "tags": sorted(tags)})
        prof.equipped_ids[b["id"]] = prof.equipped_ids.get(b["id"], 0) + 1
        prof.weapons += bool(tags & {"Weapon", "ShootsBullets"})
        prof.bullet_mods += "BulletModifier" in tags
        prof.attack_mods += "AttackModifier" in tags
        prof.weapon_mods += "WeaponModifier" in tags
        prof.generators += "EnergyGenerator" in tags
        prof.consumers += "EnergyConsumer" in tags
        prof.actives += "Active" in tags
    return prof


def _modifier_targets(tags: list[str]) -> list[str]:
    if "BulletModifier" in tags:
        return ["CanBeBulletModified"]
    if "AttackModifier" in tags:
        return ["Weapon", "CanBeAttackModified"]
    if "WeaponModifier" in tags:
        return ["Weapon"]
    return []


def _hp_ratio(state: JSON) -> float:
    p = state.get("player") or {}
    return float(p.get("hp", 1)) / max(1.0, float(p.get("max_hp", 1)))


def score_bodypart(opt: JSON, prof: BuildProfile, state: JSON, catalog: Catalog) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    warnings: list[str] = []
    bid = opt.get("id", "")
    tags = list(opt.get("tags") or catalog.tags(bid))
    rarity = opt.get("rarity") or ""
    rarity_idx = RARITY_IDX.get(rarity, 0)
    score = 5.0 + rarity_idx * 4
    if rarity_idx > 0:
        reasons.append(f"{rarity} rarity")

    targets_tags = _modifier_targets(tags)
    if targets_tags:
        targets = [b for b in prof.equipped if any(t in b["tags"] for t in targets_tags)]
        if targets:
            score += 3 + 3 * len(targets)
            names = ", ".join(b.get("name") or b["id"] for b in targets[:3])
            reasons.append(f"Modifies {len(targets)} equipped weapon{'s' if len(targets) > 1 else ''} ({names})")
        else:
            score -= 2
            warnings.append("Nothing equipped can be modified by this yet")

    if WEAPON_TAGS & set(tags):
        score += 4 + prof.modifiers * 1.5
        if prof.modifiers:
            plural = "s" if prof.modifiers > 1 else ""
            reasons.append(f"{prof.modifiers} modifier organelle{plural} in build can buff it")
        if prof.weapons == 0:
            score += 2
            reasons.append("You have no weapon yet")

    if "EnergyGenerator" in tags:
        deficit = prof.consumers - prof.generators
        if deficit > 0:
            score += 4 + deficit * 2
            reasons.append(f"Energy deficit: {prof.consumers} consumers vs {prof.generators} generators")
        else:
            score += 1
            reasons.append("Energy already covered")
    if "EnergyConsumer" in tags:
        spare = prof.generators - prof.consumers
        if spare > 0:
            score += 3 + spare
            reasons.append(f"Spare charge capacity: {spare} generator surplus")
        else:
            warnings.append("No spare generator capacity — may run undercharged")
    if "Active" in tags and prof.actives == 0:
        reasons.append("Adds an active ability")

    needs = opt.get("needs_connection") or catalog.bodyparts.get(bid, {}).get("needs_connection_warning") or []
    for need in needs:
        if not any(need in b["tags"] or (need == "Weapon" and "ShootsBullets" in b["tags"]) for b in prof.equipped):
            warnings.append(f"Wants an adjacent {need} — none in current build")

    if prof.equipped_ids.get(bid, 0) > 0 and rarity != "Legendary":
        score += 3
        reasons.append("Duplicate of an equipped part — can combine to raise rarity")

    name = opt.get("name") or catalog.bodyparts.get(bid, {}).get("name") or ""
    if _hp_ratio(state) < 0.4 and DEFENSIVE_NAME.search(name):
        score += 3
        reasons.append("Defensive value while HP is low")
    return score, reasons, warnings


def score_mutation(opt: JSON, prof: BuildProfile, state: JSON) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    warnings: list[str] = []
    text = f"{opt.get('id', '')} {opt.get('description', '')}".lower()
    score = 5.0

    def has(pattern: str) -> bool:
        return re.search(pattern, text) is not None

    if opt.get("id") == "skip_evolution":
        return 0.0, ["Skips the evolution"], []
    if has(r"damage|attack"):
        score += 3 + prof.weapons
        if prof.weapons:
            reasons.append(f"Scales with your {prof.weapons} weapon{'s' if prof.weapons > 1 else ''}")
    if has(r"speed|dodge|move"):
        score += 3
        reasons.append("Mobility")
    if has(r"health|heal|armor|\bhp\b"):
        score += 2
        if _hp_ratio(state) < 0.5:
            score += 3
            reasons.append("Survivability while HP is low")
    if has(r"energy|charge|stamina"):
        deficit = max(0, prof.consumers - prof.generators)
        score += 2 + deficit
        if deficit:
            reasons.append("Helps your energy deficit")
    if has(r"money|pickup|dna|drop"):
        score += 1.5
        reasons.append("Economy")
    if has(r"slot"):
        score += 2
        reasons.append("Extra slots permanently widen the build")
    if opt.get("type") == "evolution":
        score += 4 + prof.weapons
        reasons.append("Evolution: changes your body layout")
        if opt.get("bonus_damage"):
            reasons.append(f"+{round(float(opt['bonus_damage']) * 100)}% damage")
        if opt.get("bonus_hp"):
            reasons.append(f"+{opt['bonus_hp']} max HP")
    if not reasons:
        reasons.append("General-purpose pick")
    return score, reasons, warnings


def _label(opt: JSON) -> str:
    name = opt.get("name") or opt.get("id") or "item"
    if opt.get("type") in ("mutation", "evolution"):
        return f"{name} ({opt['type']})"
    if opt.get("rarity"):
        return f"{name} · {opt['rarity']}"
    return str(name)


def score_option(opt: JSON, prof: BuildProfile, state: JSON, catalog: Catalog) -> Scored:
    kind = opt.get("type")
    if kind in ("mutation", "evolution"):
        score, reasons, warnings = score_mutation(opt, prof, state)
    elif kind == "bodypart":
        score, reasons, warnings = score_bodypart(opt, prof, state, catalog)
    elif kind == "pickup" and opt.get("is_health"):
        low = _hp_ratio(state) < 0.7
        score, reasons, warnings = (7.0 if low else 2.0), ["Healing pickup" + (" — you're hurt" if low else "")], []
    else:
        score, reasons, warnings = 3.0, [], ["Unrecognised item; no scoring rules"]
    return Scored(
        key=str(opt.get("key", opt.get("id", ""))),
        label=_label(opt),
        score=score,
        reasons=reasons,
        warnings=warnings,
        option=opt,
    )


def _apply_shop_cost(s: Scored, opt: JSON, state: JSON) -> None:
    p = state.get("player") or {}
    cost = int(opt.get("cost") or 0)
    if opt.get("pay_with_blood"):
        max_hp = int(p.get("max_hp", 0))
        s.warnings.append(f"Costs {cost} max HP (blood)")
        if max_hp <= cost + 1:
            s.warnings.append("Would leave you at 1 max HP or less")
            s.score -= 20
        elif max_hp - cost <= 3:
            s.warnings.append("Leaves you fragile")
        s.label += f" — {cost} HP"
    else:
        money = int(p.get("money", 0))
        if cost > money:
            s.warnings.append(f"Can't afford ({cost} > {money})")
            s.score -= 100
        s.label += f" — {cost}¢"
    s.score_per_cost = s.score / cost if cost else s.score


def recommend(state: JSON | None, catalog: Catalog) -> JSON:
    if not state or not state.get("in_run"):
        return {"ok": False, "groups": []}
    prof = build_profile(state, catalog)
    groups = []
    for group in state.get("choices", []):
        picks = [score_option(o, prof, state, catalog) for o in group.get("options", [])]
        if group.get("kind") == "shop":
            for s in picks:
                _apply_shop_cost(s, s.option, state)
            picks.sort(key=lambda s: s.score_per_cost or 0.0, reverse=True)
        else:
            picks.sort(key=lambda s: s.score, reverse=True)
        title = {
            "reward": "Pick one" if group.get("exclusive") else "Reward",
            "shop": "Shop",
            "level_up": "Level-up",
        }.get(group.get("kind", ""), "Choice")
        groups.append(
            {
                "choice_id": group.get("choice_id"),
                "kind": group.get("kind"),
                "title": title,
                "exclusive": bool(group.get("exclusive")),
                "picks": [s.to_json() for s in picks],
            }
        )
    order = {"level_up": 0, "reward": 1, "shop": 2}
    groups.sort(key=lambda g: order.get(g["kind"] or "", 9))
    return {"ok": True, "groups": groups}
