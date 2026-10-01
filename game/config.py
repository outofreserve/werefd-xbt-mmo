"""Tunable economic constants for We're F'd: An XBT MMO.

Everything that affects game balance lives here so the economy can be
retuned without touching engine logic.
"""

# --- Networking ---
HOST = "0.0.0.0"
PORT = 6565

# --- Accounts ---
STARTING_FIAT = 1000.0          # Granted to a new player, and added to total fiat supply.
MIN_PASSWORD_LEN = 4            # Passwords cannot be recovered -- players must write them down.

# --- Fiat interest (feeds the action pool) ---
FIAT_APY = 0.10                 # 10% annual rate, compounded every tick.
TICK_SECONDS = 1.0              # Interest + electricity billing cadence.
SECONDS_PER_YEAR = 365 * 24 * 3600
# Per-tick compounding rate derived from the APY.
FIAT_TICK_RATE = (1.0 + FIAT_APY) ** (TICK_SECONDS / SECONDS_PER_YEAR) - 1.0

# --- XBT-Hash (mining hardware) ---
HASH_UNIT_GHS = 1.0              # 1 XBT-Hash unit = 1 GH/s.
HASH_PRICE_FIAT = 100.0          # One-time fiat cost per GH/s of hash power.
WATTS_PER_GHS = 1.0              # Electricity draw per GH/s.
ELECTRICITY_PRICE_PER_KWH = 0.10 # Game electricity price.
# Fiat cost per GH/s per tick: W -> kWh over TICK_SECONDS -> fiat.
ELECTRICITY_COST_PER_GHS_PER_TICK = (
    WATTS_PER_GHS * (TICK_SECONDS / 3600.0) / 1000.0
) * ELECTRICITY_PRICE_PER_KWH

# --- Mining / block rewards ---
BLOCK_REWARD_XBT = 50.0
BLOCK_INTERVAL_SECONDS = 600     # 10 minutes.

# --- Automated Market Maker (XBT <-> fiat) ---
# House-seeded virtual liquidity (constant-product x*y=k). Not part of the
# player fiat supply; this is the "exchange", not a player wallet.
AMM_SEED_FIAT = 50_000.0
AMM_SEED_XBT = 1_000.0
AMM_FEE_RATE = 0.003             # 0.3% swap fee, paid into the fiat pool.

# --- Actions (draw from / pay into the shared fiat pool) ---
# cost: fiat stake required to attempt the action.
# win_chance: probability of success.
# reward: fiat paid out of the pool on success (capped to pool balance).
# cooldown: seconds between attempts per player.
ACTIONS = {
    "GOBLIN": {"cost": 10.0, "win_chance": 0.70, "reward": 25.0, "cooldown": 30},
    "DRAGON": {"cost": 100.0, "win_chance": 0.30, "reward": 400.0, "cooldown": 300},
    "QUEST": {"cost": 0.0, "win_chance": 1.0, "reward": (5.0, 15.0), "cooldown": 120},
}

DB_PATH = "werefd.db"

# --- World travel ---
TRAVEL_SECONDS = 15.0   # time a TRAVEL hop takes; not instant.

# --- Ephemeral local chat ---
CHAT_MESSAGE_TTL_SECONDS = 60.0  # chat is never persisted; it just expires.
