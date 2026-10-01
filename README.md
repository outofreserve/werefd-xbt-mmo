# We're F'd: An XBT MMO

A lightweight, text-based, multiplayer currency & resource management game
played over raw TCP. Stdlib-only Python (`asyncio` + `sqlite3`) -- no
dependencies to install. Connect with `nc`, `telnet`, or the bundled
`client.py`.

## Running the server

```
python3 server.py
```

Listens on `0.0.0.0:6565` by default (see `game/config.py`). Game state
persists to `werefd.db` (SQLite) in the working directory, so restarts are
safe.

## Playing

```
nc 127.0.0.1 6565
```
or
```
python3 client.py 127.0.0.1 6565
```

### Commands

| Command | Description |
|---|---|
| `REGISTER <user> <pass>` | Create an account. **Password cannot ever be recovered -- write it down.** |
| `LOGIN <user> <pass>` | Log in |
| `DASHBOARD` / `SKILLS` / `INVENTORY` / `QUESTS` / `COMPANIONS` / `MAP` | ANSI overview screens |
| `STATUS` | Fiat balance, XBT balance, hash power, XBT price, location |
| `BUY HASH <n>` | Buy `n` GH/s of XBT-Hash hardware |
| `TRAVEL <direction>` | Move to a connected location (see `MAP`) |
| `TRAIN <skill> <action>` | Train a skill, e.g. `TRAIN FISHING SHRIMP` |
| `BUY COMPANION <species>` | Buy a companion with XBT (shop species only) |
| `SET COMPANION <id>` | Make an owned companion your active combatant |
| `PVE <monster>` | Fight a wild monster at your location |
| `DUEL CHALLENGE <user>` | Challenge another player to a staked duel |
| `DUEL STAKE FIAT\|XBT\|ITEM\|COMPANION ...` | Set your stake for the pending duel |
| `DUEL ACCEPT` / `DUEL CANCEL` / `DUEL STATUS` | Resolve, cancel, or inspect your pending duel |
| `MARKET PRICE` | Current XBT/fiat exchange price |
| `MARKET BUY <fiat>` | Spend fiat to buy XBT on the AMM |
| `MARKET SELL <xbt>` | Sell XBT for fiat on the AMM |
| `FIGHT GOBLIN` / `FIGHT DRAGON` | Risk a fiat stake for a shot at a pool payout |
| `QUEST` | Free, guaranteed small payout (on cooldown) |
| `HELP` | List commands |
| `QUIT` | Disconnect |

## Game design

### Accounts
New players register a username/password (hashed with PBKDF2-SHA256,
unique salt per account -- there is no recovery mechanism by design, so
players must write their password down). Joining grants **$1,000 fiat**,
which is simultaneously added to the game's total fiat supply.

### Fiat & the pool
The total fiat supply accrues interest continuously at a **10% APY**,
compounded every server tick (1s). That interest is *not* handed to
players directly -- it flows into a shared **pool**. The pool is what
funds action payouts (see below) and is also fed by: hash hardware
purchases, electricity payments, AMM swap fees, and stakes lost in
failed actions. This keeps total fiat supply fully accounted for: it only
grows from new-player grants and interest, never silently.

### XBT-Hash & mining
Players buy **XBT-Hash** units (`BUY HASH <n>`), each granting 1 GH/s of
hash power, priced in fiat (`HASH_PRICE_FIAT` in config). Every GH/s
continuously draws **1 watt**, billed every tick at **$0.10/kWh**
(a tiny, steady drain). The game starts with **0 XBT** in existence.
Every **10 minutes**, a **50 XBT** block reward is split across all
players proportional to their *paid-for* active hash power that interval
-- exactly like a simplified mining pool. If a player can't cover their
electricity bill, their hash power is skipped for that block (it isn't
destroyed -- it resumes earning once they top up their fiat).

### Exchange (AMM)
XBT and fiat trade through a constant-product automated market maker
(`x*y=k`), seeded with house liquidity (`AMM_SEED_FIAT` /
`AMM_SEED_XBT`). Price moves with trade volume in either direction; a
0.3% fee on every swap flows into the pool. This is how players convert
mined XBT into fiat to pay electricity bills, or speculate the other way.

### Actions (fight the pool)
`FIGHT GOBLIN`, `FIGHT DRAGON`, and `QUEST` let players risk a fiat stake
(or nothing, for `QUEST`) against a win chance. Winning pays out of the
shared pool (capped to whatever the pool can afford); losing sends the
stake into the pool. Each action has its own cooldown. Tune odds/costs in
`game/config.py` under `ACTIONS`.

### World & regions
Players start at the **Wilderness Camp** and `TRAVEL <direction>` between
connected locations (`MAP` shows the world and your position). Regions are
declarative in `game/world.py` -- adding a new one later is just a new
`Location` entry plus exits linking it in. Skills and monsters are tied to
specific locations (e.g. Fishing at Riverside, Mining at the Old Quarry).

### Skills (RuneScape-style)
Each skill has a classic XP curve (levels 1-99, `game/skills/base.py`)
driving a `TRAIN <skill> <action>` loop: gathering skills (Fishing,
Mining) always succeed and scale yield/unlocks by level; processing
skills (Cooking) consume an ingredient and can fail ("burn") with a
chance that shrinks as level rises. **Adding a new skill is a 3-step
recipe:** create `game/skills/<name>.py` defining a `Skill` + its
`SkillAction`s (see `fishing.py` for the template), call
`register_skill(...)`, then add one import line to
`game/skills/__init__.py`. The dashboard, `SKILLS` screen, and `TRAIN`
command all work automatically off the registry -- no other code changes.

### Companions & combat
Companions (`game/companions.py`) are simple stat blocks (HP/attack/
defense) acquired by defeating wild monsters (`PVE <monster>`, chance to
tame), as quest rewards, or purchased with XBT (`BUY COMPANION
<species>`). `SET COMPANION <id>` makes one active; combat uses your
active companion's stats (or weak bare-handed stats if you have none).
Combat itself (`game/combat.py`) is simple turn-based stat exchange for
v1, with room to layer ability cards on top later without changing the
player-facing commands.

PvP is **mutual, staked duels only** -- no unsolicited ganking:
`DUEL CHALLENGE <user>`, then both sides `DUEL STAKE FIAT|XBT|ITEM|
COMPANION ...`, and the challenged player `DUEL ACCEPT` to resolve it
instantly; the winner takes the loser's stake.

### Quests
Declarative in `game/quests.py`: an id, a `check(username)` predicate
re-evaluated against live player state, and a reward (fiat/items/
companion). The tutorial quest ("Journey to Town") auto-starts on
registration and completes the moment you arrive. New quests are just new
entries -- the engine re-checks all of a player's active quests after
every command.

### Dashboard
`DASHBOARD`, `SKILLS`, `INVENTORY`, `QUESTS`, `COMPANIONS`, and `MAP` are
ANSI-redrawn text screens (`game/ui.py`) -- they clear and repaint the
screen like a lightweight TUI, but are just bytes, so they render
correctly over raw `nc`/`telnet` with no special client required.

## Project layout

```
server.py            Entry point: TCP server, protocol, connection handling
client.py             Optional thin terminal client
game/config.py        Tunable economy constants
game/db.py            SQLite schema & accessors
game/economy.py       Interest, electricity billing, mining, AMM, pool actions
game/world.py          Locations & travel graph
game/items.py          Item catalog
game/skills/           Skill framework + one module per skill (fishing/mining/cooking)
game/training.py       TRAIN command resolution
game/travel.py          TRAVEL command resolution
game/companions.py     Companion species catalog
game/monsters.py       Wild monster catalog
game/combat.py          PvE fights + staked PvP duels
game/quests.py          Quest framework & definitions
game/ui.py              ANSI dashboard screens
tests/                 Unit tests (economy, skills, world, quests, combat, duels)
```

## Tests

```
python3 -m unittest discover -s tests
```
