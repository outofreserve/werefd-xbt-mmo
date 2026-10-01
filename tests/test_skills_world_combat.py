import os
import tempfile
import unittest

from game import battle, combat, combat_stats, companions, config, db, equipment, items, quests, training, travel, world
import game.skills  # noqa: F401
from game.skills.base import level_for_xp, xp_for_level, success_chance, SKILLS


class SkillMathTestCase(unittest.TestCase):
    def test_level_1_requires_zero_xp(self):
        self.assertEqual(level_for_xp(0), 1)

    def test_known_xp_milestones(self):
        # Standard RuneScape-style curve sanity checks.
        self.assertEqual(xp_for_level(1), 0)
        self.assertGreater(xp_for_level(2), 0)
        self.assertLess(xp_for_level(2), xp_for_level(10))
        self.assertLess(xp_for_level(50), xp_for_level(99))

    def test_level_monotonic_with_xp(self):
        prev = 1
        for xp in range(0, 50000, 500):
            lvl = level_for_xp(xp)
            self.assertGreaterEqual(lvl, prev)
            prev = lvl

    def test_success_chance_scales_up_with_level(self):
        action = SKILLS["COOKING"].action("shrimp")
        low = success_chance(action, action.level_req)
        high = success_chance(action, 99)
        self.assertAlmostEqual(low, action.base_success)
        self.assertGreater(high, low)
        self.assertLessEqual(high, 1.0)

    def test_gathering_actions_always_succeed(self):
        action = SKILLS["FISHING"].action("shrimp")
        self.assertEqual(success_chance(action, 1), 1.0)


class WorldSkillsIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_path = config.DB_PATH
        self._orig_travel_seconds = config.TRAVEL_SECONDS
        config.DB_PATH = os.path.join(self.tmpdir, "test.db")
        config.TRAVEL_SECONDS = 0  # instant for most tests; delay is covered separately below.
        db.init_db()
        db.create_player("tester", "password")
        quests.start_default_quests("tester")

    def tearDown(self):
        config.DB_PATH = self._orig_db_path
        config.TRAVEL_SECONDS = self._orig_travel_seconds

    def test_new_player_starts_at_camp(self):
        player = db.get_player("tester")
        self.assertEqual(player.location, world.STARTING_LOCATION)

    def test_cannot_travel_invalid_direction(self):
        ok, msg = travel.travel("tester", "north")
        self.assertFalse(ok)
        self.assertIn("Exits", msg)

    def test_travel_updates_location(self):
        ok, _ = travel.travel("tester", "east")
        self.assertTrue(ok)
        self.assertEqual(db.get_player("tester").location, "riverside")

    def test_cannot_train_skill_at_wrong_location(self):
        # tester starts at camp; FISHING requires riverside.
        ok, msg = training.train("tester", "FISHING", "shrimp")
        self.assertFalse(ok)
        self.assertIn("right location", msg)

    def test_train_fishing_grants_item_and_xp(self):
        travel.travel("tester", "east")  # camp -> riverside
        ok, msg = training.train("tester", "FISHING", "shrimp")
        self.assertTrue(ok)
        self.assertEqual(db.get_item_qty("tester", "raw_shrimp"), 1)
        self.assertGreater(db.get_xp("tester", "FISHING"), 0)

    def test_train_locked_action_rejected(self):
        travel.travel("tester", "east")
        ok, msg = training.train("tester", "FISHING", "trout")  # needs level 20
        self.assertFalse(ok)
        self.assertIn("Requires", msg)

    def test_train_cooldown_enforced(self):
        travel.travel("tester", "east")
        training.train("tester", "FISHING", "shrimp")
        ok, msg = training.train("tester", "FISHING", "shrimp")
        self.assertFalse(ok)
        self.assertIn("ready", msg)

    def test_cooking_consumes_ingredient(self):
        travel.travel("tester", "east")
        training.train("tester", "FISHING", "shrimp")
        travel.travel("tester", "east")  # riverside -> town
        ok, msg = training.train("tester", "COOKING", "shrimp")
        self.assertTrue(ok)
        self.assertEqual(db.get_item_qty("tester", "raw_shrimp"), 0)
        got_cooked = db.get_item_qty("tester", "cooked_shrimp")
        got_burnt = db.get_item_qty("tester", "burnt_food")
        self.assertEqual(got_cooked + got_burnt, 1)

    def test_cooking_without_ingredient_fails(self):
        travel.travel("tester", "east")
        travel.travel("tester", "east")
        ok, msg = training.train("tester", "COOKING", "shrimp")
        self.assertFalse(ok)
        self.assertIn("need", msg.lower())

    def test_journey_to_town_quest_completes_on_arrival(self):
        self.assertEqual(db.get_quest_status("tester", "journey_to_town"), "active")
        travel.travel("tester", "east")
        travel.travel("tester", "east")  # camp -> riverside -> town
        messages = quests.check_and_complete("tester")
        self.assertTrue(any("Journey to Town" in m for m in messages))
        self.assertEqual(db.get_quest_status("tester", "journey_to_town"), "awaiting_choice")
        player = db.get_player("tester")
        self.assertGreater(player.fiat, config.STARTING_FIAT)  # reward fiat granted
        comps = db.get_companions("tester")
        self.assertTrue(any(c["species_id"] == "pebble" for c in comps))
        ok, _ = quests.choose_reward("tester", "sword")
        self.assertTrue(ok)
        self.assertEqual(db.get_quest_status("tester", "journey_to_town"), "complete")

    def test_quest_does_not_complete_twice(self):
        travel.travel("tester", "east")
        travel.travel("tester", "east")
        quests.check_and_complete("tester")
        fiat_after_first = db.get_player("tester").fiat
        messages = quests.check_and_complete("tester")
        self.assertEqual(messages, [])
        self.assertEqual(db.get_player("tester").fiat, fiat_after_first)


class CombatTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmpdir, "test.db")
        db.init_db()
        db.create_player("hero", "password")
        db.create_player("villain", "password")

    def tearDown(self):
        config.DB_PATH = self._orig_db_path
        battle.ACTIVE_BATTLES.clear()

    def test_bare_handed_profile_is_weak_without_weapon(self):
        profile = combat_stats.player_combat_profile("hero")
        self.assertEqual(profile.damage_type, "melee")
        self.assertAlmostEqual(profile.power, config.BASE_UNARMED_DAMAGE + config.STR_DAMAGE_PER_LEVEL)

    def test_pve_requires_correct_location(self):
        ok, msg = battle.start_pve("hero", "boar")  # hero starts at camp, which has boar
        self.assertTrue(ok)
        self.assertTrue(battle.in_combat("hero"))

    def test_pve_unknown_monster(self):
        ok, msg = battle.start_pve("hero", "dragon_lord")
        self.assertFalse(ok)
        self.assertIn("Unknown monster", msg)

    def test_cannot_start_second_pve_while_in_combat(self):
        battle.start_pve("hero", "boar")
        ok, msg = battle.start_pve("hero", "boar")
        self.assertFalse(ok)
        self.assertIn("already in combat", msg)

    def test_pve_cooldown_enforced_after_battle_ends(self):
        now = 1000.0
        battle.start_pve("hero", "boar", now=now)
        bt = battle.get_battle("hero")
        bt.b.hp = 0.1  # force the next swing to finish the fight
        battle.process_tick(now=now + bt.a.attack_interval + 1)
        self.assertFalse(battle.in_combat("hero"))
        ok, msg = battle.start_pve("hero", "boar", now=now + bt.a.attack_interval + 2)
        self.assertFalse(ok)
        self.assertIn("recovering", msg)

    def test_pve_victory_pays_fiat_and_resolves_battle(self):
        now = 1000.0
        with db.connect() as conn:
            conn.execute("UPDATE game_state SET pool_fiat = 1000 WHERE id = 1")
        battle.start_pve("hero", "boar", now=now)
        bt = battle.get_battle("hero")
        bt.b.hp = 0.1
        fiat_before = db.get_player("hero").fiat
        battle.process_tick(now=now + bt.a.attack_interval + 1)
        self.assertFalse(battle.in_combat("hero"))
        self.assertGreater(db.get_player("hero").fiat, fiat_before)

    def test_attack_grants_attribute_xp(self):
        now = 1000.0
        battle.start_pve("hero", "boar", now=now)
        self.assertGreater(db.get_xp("hero", "STRENGTH"), 0)

    def test_flee_success_ends_combat(self):
        import random
        now = 1000.0
        battle.start_pve("hero", "boar", now=now)
        orig = random.random
        random.random = lambda: 0.0  # guarantees the flee roll succeeds
        try:
            ok, msg, pushes = battle.flee("hero", now=now + 1)
        finally:
            random.random = orig
        self.assertTrue(ok)
        self.assertFalse(battle.in_combat("hero"))

    def test_flee_failure_keeps_combat_active(self):
        import random
        now = 1000.0
        battle.start_pve("hero", "boar", now=now)
        orig = random.random
        random.random = lambda: 0.999  # guarantees the flee roll fails
        try:
            ok, msg, pushes = battle.flee("hero", now=now + 1)
        finally:
            random.random = orig
        self.assertFalse(ok)
        self.assertTrue(battle.in_combat("hero"))

    def test_duel_challenge_and_fiat_stake_transfer(self):
        ok, msg = combat.challenge("hero", "villain")
        self.assertTrue(ok)
        duel = db.get_pending_duel_for("hero")
        ok, _ = combat.set_stake("hero", duel["id"], {"type": "fiat", "amount": 100.0})
        self.assertTrue(ok)
        ok, _ = combat.set_stake("villain", duel["id"], {"type": "fiat", "amount": 50.0})
        self.assertTrue(ok)

        hero_before = db.get_player("hero").fiat
        villain_before = db.get_player("villain").fiat
        now = 2000.0
        ok, msg = combat.accept(duel["id"], "villain", now=now)
        self.assertTrue(ok)
        self.assertTrue(battle.in_combat("hero"))
        self.assertTrue(battle.in_combat("villain"))

        bt = battle.get_battle("hero")
        bt.b.hp = 0.1  # force a winner on the next swing
        battle.process_tick(now=now + bt.a.attack_interval + 1)
        self.assertFalse(battle.in_combat("hero"))
        self.assertFalse(battle.in_combat("villain"))

        hero_after = db.get_player("hero").fiat
        villain_after = db.get_player("villain").fiat
        total_before = hero_before + villain_before
        total_after = hero_after + villain_after
        self.assertAlmostEqual(total_before, total_after, places=6)
        resolved = db.get_duel(duel["id"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertIn(resolved["winner"], ("hero", "villain"))

    def test_duel_cannot_challenge_self(self):
        ok, msg = combat.challenge("hero", "hero")
        self.assertFalse(ok)

    def test_duel_cancel(self):
        combat.challenge("hero", "villain")
        duel = db.get_pending_duel_for("hero")
        ok, _ = combat.cancel(duel["id"], "hero")
        self.assertTrue(ok)
        self.assertIsNone(db.get_pending_duel_for("hero"))

    def test_duel_invalid_stake_cancels_on_accept(self):
        combat.challenge("hero", "villain")
        duel = db.get_pending_duel_for("hero")
        # Hero stakes more fiat than they actually have.
        combat.set_stake("hero", duel["id"], {"type": "fiat", "amount": 10.0})
        with db.connect() as conn:
            conn.execute("UPDATE players SET fiat = 0 WHERE username = 'hero'")
        ok, msg = combat.accept(duel["id"], "villain")
        self.assertFalse(ok)
        self.assertIn("cancelled", msg.lower())


class EquipmentTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmpdir, "test.db")
        db.init_db()
        db.create_player("hero", "password")

    def tearDown(self):
        config.DB_PATH = self._orig_db_path
        battle.ACTIVE_BATTLES.clear()

    def test_cannot_equip_item_not_owned(self):
        ok, msg = equipment.equip("hero", "bronze_sword")
        self.assertFalse(ok)

    def test_equip_applies_weapon_bonus(self):
        db.add_item("hero", "bronze_sword", 1)
        ok, msg = equipment.equip("hero", "bronze_sword")
        self.assertTrue(ok)
        profile = combat_stats.player_combat_profile("hero")
        self.assertEqual(profile.damage_type, "melee")
        self.assertAlmostEqual(
            profile.power, config.BASE_UNARMED_DAMAGE + (1 + 1.0) * config.STR_DAMAGE_PER_LEVEL
        )

    def test_selling_equipped_weapon_drops_bonus(self):
        db.add_item("hero", "wooden_bow", 1)
        equipment.equip("hero", "wooden_bow")
        self.assertEqual(combat_stats.player_combat_profile("hero").damage_type, "ranged")
        db.remove_item("hero", "wooden_bow", 1)
        self.assertEqual(combat_stats.player_combat_profile("hero").damage_type, "melee")

    def test_cannot_equip_mid_combat(self):
        db.add_item("hero", "bronze_sword", 1)
        battle.start_pve("hero", "boar")
        ok, msg = equipment.equip("hero", "bronze_sword")
        self.assertFalse(ok)


class QuestChoiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_path = config.DB_PATH
        self._orig_travel_seconds = config.TRAVEL_SECONDS
        config.DB_PATH = os.path.join(self.tmpdir, "test.db")
        config.TRAVEL_SECONDS = 0
        db.init_db()
        db.create_player("tester", "password")
        quests.start_default_quests("tester")
        travel.travel("tester", "east")
        travel.travel("tester", "east")  # camp -> riverside -> town

    def tearDown(self):
        config.DB_PATH = self._orig_db_path
        config.TRAVEL_SECONDS = self._orig_travel_seconds

    def test_quest_completion_awaits_weapon_choice(self):
        messages = quests.check_and_complete("tester")
        self.assertTrue(any("Journey to Town" in m for m in messages))
        self.assertEqual(db.get_quest_status("tester", "journey_to_town"), "awaiting_choice")
        self.assertEqual(db.get_item_qty("tester", "bronze_sword"), 0)

    def test_choosing_grants_and_equips_weapon(self):
        quests.check_and_complete("tester")
        ok, msg = quests.choose_reward("tester", "sword")
        self.assertTrue(ok)
        self.assertEqual(db.get_quest_status("tester", "journey_to_town"), "complete")
        self.assertEqual(db.get_item_qty("tester", "bronze_sword"), 1)
        self.assertEqual(db.get_player("tester").equipped_weapon, "bronze_sword")

    def test_invalid_choice_rejected(self):
        quests.check_and_complete("tester")
        ok, msg = quests.choose_reward("tester", "shield")
        self.assertFalse(ok)


class DelayedTravelTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_path = config.DB_PATH
        self._orig_travel_seconds = config.TRAVEL_SECONDS
        config.DB_PATH = os.path.join(self.tmpdir, "test.db")
        config.TRAVEL_SECONDS = 15.0
        db.init_db()
        db.create_player("wanderer", "password")

    def tearDown(self):
        config.DB_PATH = self._orig_db_path
        config.TRAVEL_SECONDS = self._orig_travel_seconds

    def test_travel_is_not_instant(self):
        now = 1000.0
        ok, msg = travel.travel("wanderer", "east", now=now)
        self.assertTrue(ok)
        self.assertIn("Arriving in 15s", msg)
        self.assertEqual(db.get_player("wanderer").location, "camp")  # not there yet

    def test_cannot_start_second_trip_mid_travel(self):
        now = 1000.0
        travel.travel("wanderer", "east", now=now)
        ok, msg = travel.travel("wanderer", "east", now=now + 1)
        self.assertFalse(ok)
        self.assertIn("already on your way", msg)

    def test_arrival_resolves_once_time_passes(self):
        now = 1000.0
        travel.travel("wanderer", "east", now=now)
        travel.resolve_arrival("wanderer", now=now + 20)
        self.assertEqual(db.get_player("wanderer").location, "riverside")

    def test_training_blocked_while_travelling(self):
        now = 1000.0
        travel.travel("wanderer", "east", now=now)
        ok, msg = training.train("wanderer", "FISHING", "shrimp", now=now + 1)
        self.assertFalse(ok)
        self.assertIn("on the road", msg)

    def test_pve_blocked_while_travelling(self):
        now = 1000.0
        travel.travel("wanderer", "east", now=now)
        ok, msg = battle.start_pve("wanderer", "boar", now=now + 1)
        self.assertFalse(ok)
        self.assertIn("on the road", msg)


class ResourceNodeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmpdir, "test.db")
        db.init_db()
        db.create_player("miner", "password")
        with db.connect() as conn:
            conn.execute("UPDATE players SET location = 'quarry' WHERE username = 'miner'")
        db.add_xp("miner", "MINING", 500000)  # plenty of levels for iron/gold

    def tearDown(self):
        config.DB_PATH = self._orig_db_path

    def test_gold_node_depletes_after_use(self):
        now = 2000.0
        ok, msg = training.train("miner", "MINING", "gold", now=now)
        self.assertTrue(ok)
        self.assertIn("tapped out", msg)
        ok2, msg2 = training.train("miner", "MINING", "gold", now=now + 3)
        self.assertFalse(ok2)
        self.assertIn("depleted", msg2)

    def test_gold_node_respawns_after_cooldown(self):
        now = 2000.0
        training.train("miner", "MINING", "gold", now=now)
        ok, msg = training.train("miner", "MINING", "gold", now=now + 181)
        self.assertTrue(ok)

    def test_two_iron_veins_allow_two_miners_before_depletion(self):
        now = 3000.0
        ok1, _ = training.train("miner", "MINING", "iron", now=now)
        self.assertTrue(ok1)
        ok2, _ = training.train("miner", "MINING", "iron", now=now + 3)  # second vein still up
        self.assertTrue(ok2)
        ok3, msg3 = training.train("miner", "MINING", "iron", now=now + 6)
        self.assertFalse(ok3)
        self.assertIn("depleted", msg3)


class ChatBufferTestCase(unittest.TestCase):
    def test_messages_visible_until_ttl(self):
        from game import chat
        chat.post("town", "alice", "hello", now=100.0)
        msgs = chat.recent("town", now=100.0 + config.CHAT_MESSAGE_TTL_SECONDS - 1)
        self.assertEqual(len(msgs), 1)

    def test_messages_expire_after_ttl(self):
        from game import chat
        chat.post("town", "alice", "hello", now=100.0)
        msgs = chat.recent("town", now=100.0 + config.CHAT_MESSAGE_TTL_SECONDS + 1)
        self.assertEqual(len(msgs), 0)


if __name__ == "__main__":
    unittest.main()
