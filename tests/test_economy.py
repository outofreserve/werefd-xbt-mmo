import os
import tempfile
import unittest

from game import config, db, economy


class EconomyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmpdir, "test.db")
        db.init_db()

    def tearDown(self):
        config.DB_PATH = self._orig_db_path

    def _state(self):
        with db.connect() as conn:
            return conn.execute("SELECT * FROM game_state WHERE id = 1").fetchone()

    def test_register_grants_starting_fiat_and_increases_supply(self):
        p = db.create_player("alice", "hunter2")
        self.assertEqual(p.fiat, config.STARTING_FIAT)
        state = self._state()
        self.assertEqual(state["total_fiat_supply"], config.STARTING_FIAT)

    def test_duplicate_username_rejected(self):
        db.create_player("bob", "password")
        with self.assertRaises(ValueError):
            db.create_player("bob", "password2")

    def test_authenticate(self):
        db.create_player("carol", "correcthorse")
        self.assertTrue(db.authenticate("carol", "correcthorse"))
        self.assertFalse(db.authenticate("carol", "wrongpass"))
        self.assertFalse(db.authenticate("nobody", "whatever"))

    def test_tick_applies_interest_to_pool_and_supply(self):
        db.create_player("dave", "password")
        with db.connect() as conn:
            # Force a tick boundary in the past so elapsed > 0.
            conn.execute("UPDATE game_state SET last_tick = last_tick - 10")
        before = self._state()
        economy.tick()
        after = self._state()
        self.assertGreater(after["pool_fiat"], before["pool_fiat"])
        self.assertGreater(after["total_fiat_supply"], before["total_fiat_supply"])
        # Interest added to pool should equal the growth in total supply.
        self.assertAlmostEqual(
            after["total_fiat_supply"] - before["total_fiat_supply"],
            after["pool_fiat"] - before["pool_fiat"],
            places=6,
        )

    def test_buy_hash_deducts_fiat_and_feeds_pool(self):
        db.create_player("erin", "password")
        ok, _ = economy.buy_hash("erin", 2)
        self.assertTrue(ok)
        player = db.get_player("erin")
        self.assertEqual(player.hash_power_ghs, 2)
        self.assertAlmostEqual(player.fiat, config.STARTING_FIAT - 2 * config.HASH_PRICE_FIAT)
        state = self._state()
        self.assertAlmostEqual(state["pool_fiat"], 2 * config.HASH_PRICE_FIAT)

    def test_buy_hash_insufficient_funds(self):
        db.create_player("frank", "password")
        ok, msg = economy.buy_hash("frank", 10_000_000)
        self.assertFalse(ok)
        self.assertIn("Need", msg)

    def test_electricity_billing_and_block_reward(self):
        db.create_player("grace", "password")
        economy.buy_hash("grace", 5)  # 5 GH/s ($500, affordable with starting fiat)
        with db.connect() as conn:
            conn.execute(
                "UPDATE game_state SET last_tick = last_tick - 600, last_block_time = last_block_time - 600"
            )
        before = db.get_player("grace")
        summary = economy.tick()
        after = db.get_player("grace")
        self.assertTrue(summary["block_paid"])
        self.assertGreater(after.xbt, 0)
        self.assertLess(after.fiat, before.fiat)  # paid electricity
        state = self._state()
        self.assertAlmostEqual(state["total_xbt_supply"], config.BLOCK_REWARD_XBT)

    def test_market_buy_and_sell_round_trip_loses_only_fee(self):
        db.create_player("heidi", "password")
        ok, _ = economy.market_buy("heidi", 1000)
        self.assertTrue(ok)
        player = db.get_player("heidi")
        self.assertGreater(player.xbt, 0)
        ok, _ = economy.market_sell("heidi", player.xbt)
        self.assertTrue(ok)
        player2 = db.get_player("heidi")
        # Lost money to fees on both legs, but shouldn't be destroyed --
        # only moved into the pool.
        self.assertLess(player2.fiat, config.STARTING_FIAT)
        state = self._state()
        self.assertGreater(state["pool_fiat"], 0)

    def test_action_cooldown_enforced(self):
        db.create_player("ivan", "password")
        ok1, _ = economy.do_action("ivan", "QUEST")
        self.assertTrue(ok1)
        ok2, msg2 = economy.do_action("ivan", "QUEST")
        self.assertFalse(ok2)
        self.assertIn("cooldown", msg2)

    def test_action_unknown(self):
        db.create_player("judy", "password")
        ok, msg = economy.do_action("judy", "NONSENSE")
        self.assertFalse(ok)
        self.assertIn("Unknown action", msg)

    def test_fiat_conservation_across_actions(self):
        """Player fiat + pool fiat should be conserved by action outcomes
        (modulo the stake moving between the two, never vanishing)."""
        db.create_player("mallory", "password")
        for _ in range(5):
            player_before = db.get_player("mallory")
            state_before = self._state()
            total_before = player_before.fiat + state_before["pool_fiat"]
            economy.do_action("mallory", "GOBLIN")
            with db.connect() as conn:
                conn.execute(
                    "UPDATE cooldowns SET last_used = last_used - 100 WHERE username = 'mallory'"
                )
            player_after = db.get_player("mallory")
            state_after = self._state()
            total_after = player_after.fiat + state_after["pool_fiat"]
            self.assertAlmostEqual(total_before, total_after, places=6)


if __name__ == "__main__":
    unittest.main()
