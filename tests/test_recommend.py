import json
import unittest
from pathlib import Path

from matrix.recommend import Catalog, merge_catalogs, recommend

FIXTURE = Path(__file__).parent / "fixtures" / "state_reward_shop_levelup.json"


def load_state():
    return json.loads(FIXTURE.read_text())


class RecommendTest(unittest.TestCase):
    def setUp(self):
        self.rec = recommend(load_state(), Catalog())
        self.groups = {g["kind"]: g for g in self.rec["groups"]}

    def test_not_in_run(self):
        self.assertEqual(recommend(None, Catalog()), {"ok": False, "groups": []})
        self.assertFalse(recommend({"in_run": False}, Catalog())["ok"])

    def test_groups_ordered_level_up_reward_shop(self):
        self.assertEqual([g["kind"] for g in self.rec["groups"]], ["level_up", "reward", "shop"])
        self.assertEqual(self.groups["reward"]["title"], "Pick one")

    def test_every_pick_has_reason_or_warning(self):
        for g in self.rec["groups"]:
            for p in g["picks"]:
                self.assertTrue(p["reasons"] or p["warnings"], p["label"])

    def test_bullet_modifier_beats_generator_with_one_bullet_weapon(self):
        picks = self.groups["reward"]["picks"]
        self.assertEqual(picks[0]["key"], "bullet_mod@Rare")
        self.assertTrue(any("Modifies 1 equipped weapon" in r for r in picks[0]["reasons"]))

    def test_generator_reports_energy_deficit(self):
        gen = next(p for p in self.groups["reward"]["picks"] if p["key"] == "generator@Common")
        self.assertTrue(any("Energy deficit" in r for r in gen["reasons"]))
        self.assertEqual(gen["warnings"], [])

    def test_shop_unaffordable_ranks_last_and_warns(self):
        picks = self.groups["shop"]["picks"]
        self.assertEqual(picks[-1]["key"], "laser@Epic#3")
        self.assertIn("Can't afford (99 > 40)", picks[-1]["warnings"])

    def test_blood_cost_warning(self):
        devil = next(p for p in self.groups["shop"]["picks"] if p["key"] == "devil@Legendary#4")
        self.assertIn("Costs 9 max HP (blood)", devil["warnings"])
        self.assertIn("Would leave you at 1 max HP or less", devil["warnings"])

    def test_duplicate_combine_reason(self):
        rifle = next(p for p in self.groups["shop"]["picks"] if p["key"] == "assault_rifle@Common#1")
        self.assertTrue(any("combine" in r for r in rifle["reasons"]))

    def test_raw_option_passed_through(self):
        bm = self.groups["reward"]["picks"][0]
        self.assertEqual(bm["option"]["tooltip"], "[b]Bullet Mod[/b]{hr}+20% damage")

    def test_damage_mutation_scales_with_weapons(self):
        self.assertEqual(self.groups["level_up"]["picks"][0]["key"], "damage_mutation")

    def test_skip_evolution_scores_zero(self):
        state = load_state()
        state["choices"] = [
            {
                "choice_id": "level_up:1:2",
                "kind": "level_up",
                "exclusive": True,
                "options": [
                    {"type": "evolution", "id": "level_1_ball_evolution", "key": "a", "bonus_hp": 2},
                    {"type": "evolution", "id": "skip_evolution", "key": "skip"},
                ],
            }
        ]
        picks = recommend(state, Catalog())["groups"][0]["picks"]
        self.assertEqual([p["key"] for p in picks], ["a", "skip"])
        self.assertIn("+2 max HP", picks[0]["reasons"])


class CatalogTest(unittest.TestCase):
    def test_live_overrides_demo_and_drops_removed(self):
        demo = {"bodyparts": [{"id": "a", "name": "A", "stats": {"x": 1}}, {"id": "gone"}], "mutations": []}
        live = {"bodyparts": [{"id": "a", "name": "A2"}, {"id": "new"}], "mutations": [{"id": "m"}]}
        cat = merge_catalogs(demo, live)
        self.assertEqual(cat.source, "live")
        self.assertEqual(set(cat.bodyparts), {"a", "new"})
        self.assertEqual(cat.bodyparts["a"], {"id": "a", "name": "A2", "stats": {"x": 1}})
        self.assertIn("m", cat.mutations)

    def test_demo_only(self):
        self.assertEqual(merge_catalogs({"bodyparts": [{"id": "a"}]}, None).source, "demo")
        self.assertEqual(merge_catalogs(None, None).source, "none")


if __name__ == "__main__":
    unittest.main()
