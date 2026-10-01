"""Core economic simulation: interest, electricity billing, mining
rewards, the AMM exchange, and action resolution.

Concurrency note: the server serializes all calls into this module behind
a single asyncio.Lock (see server.py). That keeps the SQLite writes free
of race conditions without needing row-level locking for a lightweight,
single-process game.
"""
from __future__ import annotations

import random
import time

from game import config, db


def tick(now: float | None = None) -> dict:
    """Advance the economy by one tick's worth of elapsed wall-clock time.

    Applies fiat interest (into the pool), bills every player's
    electricity, and pays out a mining block reward if the interval has
    elapsed. Returns a small summary dict for logging.
    """
    now = now if now is not None else time.time()
    summary = {"interest_added": 0.0, "electricity_billed": 0.0, "block_paid": False}

    with db.connect() as conn:
        state = conn.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
        elapsed = max(0.0, now - state["last_tick"])
        if elapsed <= 0:
            return summary

        # Compound interest on the full fiat supply, paid into the pool.
        ticks = elapsed / config.TICK_SECONDS
        interest = state["total_fiat_supply"] * (
            (1.0 + config.FIAT_TICK_RATE) ** ticks - 1.0
        )
        new_pool = state["pool_fiat"] + interest
        new_supply = state["total_fiat_supply"] + interest
        summary["interest_added"] = interest

        # Electricity billing for every player with active hash power.
        miners = conn.execute(
            "SELECT username, fiat, hash_power_ghs FROM players WHERE hash_power_ghs > 0"
        ).fetchall()
        total_active_ghs = 0.0
        billed_total = 0.0
        for m in miners:
            cost = m["hash_power_ghs"] * config.ELECTRICITY_COST_PER_GHS_PER_TICK * ticks
            charge = min(cost, m["fiat"])  # Can't go into debt; unpaid power idles.
            conn.execute(
                "UPDATE players SET fiat = fiat - ? WHERE username = ?",
                (charge, m["username"]),
            )
            billed_total += charge
            if charge >= cost - 1e-9:
                total_active_ghs += m["hash_power_ghs"]
        new_pool += billed_total
        summary["electricity_billed"] = billed_total

        # Mining block reward, proportional to active (paid-for) hash power.
        last_block_elapsed = now - state["last_block_time"]
        new_last_block_time = state["last_block_time"]
        new_xbt_supply = state["total_xbt_supply"]
        if last_block_elapsed >= config.BLOCK_INTERVAL_SECONDS and total_active_ghs > 0:
            for m in miners:
                cost = m["hash_power_ghs"] * config.ELECTRICITY_COST_PER_GHS_PER_TICK * ticks
                if min(cost, m["fiat"]) < cost - 1e-9:
                    continue  # idle this block, didn't pay for power.
                share = m["hash_power_ghs"] / total_active_ghs
                reward = config.BLOCK_REWARD_XBT * share
                conn.execute(
                    "UPDATE players SET xbt = xbt + ? WHERE username = ?",
                    (reward, m["username"]),
                )
            new_xbt_supply += config.BLOCK_REWARD_XBT
            new_last_block_time = now
            summary["block_paid"] = True

        conn.execute(
            """UPDATE game_state SET pool_fiat = ?, total_fiat_supply = ?,
               total_xbt_supply = ?, last_tick = ?, last_block_time = ?
               WHERE id = 1""",
            (new_pool, new_supply, new_xbt_supply, now, new_last_block_time),
        )
    return summary


def buy_hash(username: str, units_ghs: float) -> tuple[bool, str]:
    cost = units_ghs * config.HASH_PRICE_FIAT
    with db.connect() as conn:
        player = conn.execute(
            "SELECT fiat FROM players WHERE username = ?", (username,)
        ).fetchone()
        if player["fiat"] < cost:
            return False, f"Need ${cost:,.2f}, you only have ${player['fiat']:,.2f}."
        conn.execute(
            "UPDATE players SET fiat = fiat - ?, hash_power_ghs = hash_power_ghs + ? WHERE username = ?",
            (cost, units_ghs, username),
        )
        conn.execute("UPDATE game_state SET pool_fiat = pool_fiat + ? WHERE id = 1", (cost,))
    return True, f"Bought {units_ghs:g} GH/s for ${cost:,.2f}."


def amm_price() -> float:
    with db.connect() as conn:
        state = conn.execute(
            "SELECT amm_fiat_reserve, amm_xbt_reserve FROM game_state WHERE id = 1"
        ).fetchone()
        return state["amm_fiat_reserve"] / state["amm_xbt_reserve"]


def market_buy(username: str, fiat_amount: float) -> tuple[bool, str]:
    """Spend fiat to buy XBT from the AMM (constant product x*y=k)."""
    if fiat_amount <= 0:
        return False, "Amount must be positive."
    with db.connect() as conn:
        player = conn.execute("SELECT fiat FROM players WHERE username = ?", (username,)).fetchone()
        if player["fiat"] < fiat_amount:
            return False, f"You only have ${player['fiat']:,.2f}."
        state = conn.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
        fee = fiat_amount * config.AMM_FEE_RATE
        net_in = fiat_amount - fee
        new_fiat_reserve = state["amm_fiat_reserve"] + net_in
        xbt_out = state["amm_xbt_reserve"] - (
            state["amm_fiat_reserve"] * state["amm_xbt_reserve"] / new_fiat_reserve
        )
        if xbt_out <= 0 or xbt_out >= state["amm_xbt_reserve"]:
            return False, "Market liquidity insufficient for that trade."
        conn.execute(
            "UPDATE players SET fiat = fiat - ?, xbt = xbt + ? WHERE username = ?",
            (fiat_amount, xbt_out, username),
        )
        conn.execute(
            """UPDATE game_state SET amm_fiat_reserve = ?, amm_xbt_reserve = ?,
               pool_fiat = pool_fiat + ? WHERE id = 1""",
            (new_fiat_reserve, state["amm_xbt_reserve"] - xbt_out, fee),
        )
    return True, f"Bought {xbt_out:.8f} XBT for ${fiat_amount:,.2f} (fee ${fee:,.2f})."


def market_sell(username: str, xbt_amount: float) -> tuple[bool, str]:
    """Sell XBT into the AMM for fiat."""
    if xbt_amount <= 0:
        return False, "Amount must be positive."
    with db.connect() as conn:
        player = conn.execute("SELECT xbt FROM players WHERE username = ?", (username,)).fetchone()
        if player["xbt"] < xbt_amount:
            return False, f"You only have {player['xbt']:.8f} XBT."
        state = conn.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
        new_xbt_reserve = state["amm_xbt_reserve"] + xbt_amount
        fiat_out_gross = state["amm_fiat_reserve"] - (
            state["amm_fiat_reserve"] * state["amm_xbt_reserve"] / new_xbt_reserve
        )
        fee = fiat_out_gross * config.AMM_FEE_RATE
        fiat_out = fiat_out_gross - fee
        if fiat_out <= 0:
            return False, "Market liquidity insufficient for that trade."
        conn.execute(
            "UPDATE players SET xbt = xbt - ?, fiat = fiat + ? WHERE username = ?",
            (xbt_amount, fiat_out, username),
        )
        conn.execute(
            """UPDATE game_state SET amm_fiat_reserve = ?, amm_xbt_reserve = ?,
               pool_fiat = pool_fiat + ? WHERE id = 1""",
            (state["amm_fiat_reserve"] - fiat_out_gross, new_xbt_reserve, fee),
        )
    return True, f"Sold {xbt_amount:.8f} XBT for ${fiat_out:,.2f} (fee ${fee:,.2f})."


def do_action(username: str, action_name: str) -> tuple[bool, str]:
    action_name = action_name.upper()
    cfg = config.ACTIONS.get(action_name)
    if cfg is None:
        return False, f"Unknown action '{action_name}'. Try GOBLIN, DRAGON, or QUEST."

    now = time.time()
    last_used = db.get_cooldown(username, action_name)
    remaining = cfg["cooldown"] - (now - last_used)
    if remaining > 0:
        return False, f"{action_name} is on cooldown for {remaining:.0f}s."

    cost = cfg["cost"]
    with db.connect() as conn:
        player = conn.execute("SELECT fiat FROM players WHERE username = ?", (username,)).fetchone()
        if player["fiat"] < cost:
            return False, f"Need ${cost:,.2f} to attempt {action_name}."

        won = random.random() < cfg["win_chance"]
        state = conn.execute("SELECT pool_fiat FROM game_state WHERE id = 1").fetchone()

        if won:
            reward_cfg = cfg["reward"]
            reward = random.uniform(*reward_cfg) if isinstance(reward_cfg, tuple) else reward_cfg
            payout = min(reward, state["pool_fiat"] + cost)
            conn.execute(
                "UPDATE players SET fiat = fiat - ? + ? WHERE username = ?",
                (cost, payout, username),
            )
            # Stake flows into the pool and the payout flows back out, so
            # total fiat (player + pool) is always conserved.
            conn.execute(
                "UPDATE game_state SET pool_fiat = pool_fiat + ? - ? WHERE id = 1",
                (cost, payout),
            )
            msg = f"You defeated the {action_name.lower()}! +${payout:,.2f} (stake ${cost:,.2f} returned to pool)."
        else:
            conn.execute("UPDATE players SET fiat = fiat - ? WHERE username = ?", (cost, username))
            conn.execute("UPDATE game_state SET pool_fiat = pool_fiat + ? WHERE id = 1", (cost,))
            msg = f"You were defeated by the {action_name.lower()}. Lost ${cost:,.2f} to the pool."

    db.set_cooldown(username, action_name, now)
    return True, msg
