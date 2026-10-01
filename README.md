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
| `TRAVEL <direction>` | Set off toward a connected location -- takes time, see `MAP` |
| `TRAIN <skill> <action>` | Train a skill, e.g. `TRAIN FISHING SHRIMP` |
| `SAY <message>` | Chat to players in your current location (fades after ~60s, never saved) |
| `BUY COMPANION <species>` | Buy a companion with XBT (shop species only) |
| `SET COMPANION <id>` | Make an owned companion your active combatant |
| `PVE <monster>` | Engage a wild monster at your location in real-time auto-attack combat |
| `DUEL CHALLENGE <user>` | Challenge another player to a staked duel |
| `DUEL STAKE FIAT\|XBT\|ITEM\|COMPANION ...` | Set your stake for the pending duel |
| `DUEL ACCEPT` / `DUEL CANCEL` / `DUEL STATUS` | Resolve, cancel, or inspect your pending duel |
| `FLEE` | Attempt to disengage from your current fight (chance-based, scales with Evasion) |
| `EQUIP <item>` / `UNEQUIP` | Wield/remove a weapon from your inventory |
| `MARKET PRICE` | Current XBT/fiat exchange price |
| `MARKET BUY <fiat>` | Spend fiat to buy XBT on the AMM |
| `MARKET SELL <xbt>` | Sell XBT for fiat on the AMM |
| `FIGHT GOBLIN` / `FIGHT DRAGON` | Risk a fiat stake for a shot at a pool payout |
| `QUEST` | Free, guaranteed small payout (on cooldown) |
| `CHOOSE <option>` | Pick a quest's reward when it's awaiting your choice (e.g. `CHOOSE SWORD`) |
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

Travel is **not instant**: setting off (`TRAVEL <direction>`) starts a
timer (`TRAVEL_SECONDS` in config, 15s by default) and you arrive once it
elapses -- other actions (training, fighting, dueling) are blocked while
you're on the road. Some ores (iron, gold) come from **shared, depletable
resource nodes** (`game/resource_nodes.py`): the first player to mine one
locks it out for everyone until it respawns on its own timer, so players
genuinely race for scarce nodes while common ores (copper, tin) stay
unlimited. You can see who else is sharing your current location (in
`DASHBOARD`/`MAP`) and `SAY <message>` to chat with them -- chat is
**never persisted to the database**, living only in server memory, and
each message fades away after `CHAT_MESSAGE_TTL_SECONDS` (~60s).

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
Companions (`game/companions.py`) are simple stat blocks (attack/defense)
acquired by defeating wild monsters (`PVE <monster>`, chance to tame), as
quest rewards, or purchased with XBT (`BUY COMPANION <species>`). `SET
COMPANION <id>` makes one active, adding its attack/defense to your own.

**Combat attributes are skills too.** Strength, Dexterity, Constitution,
Evasion, and Intelligence (`game/skills/attributes.py`) level up from
fighting just like Fishing or Mining levels up from gathering -- they
drive melee/ranged/magic damage, your HP/mana pool size, and dodge
chance. HP and mana regen passively over time and are shown live on the
`DASHBOARD` as bars.

**Combat is real-time and diku-style** (`game/battle.py`): `PVE <monster>`
or `DUEL ACCEPT` starts a fight, and from then on both sides swing
automatically on their own attack-speed timer -- no turn-taking, no
per-round commands needed. Rounds resolve server-side every pulse and are
pushed straight to your terminal as they happen, until one side's HP
hits zero or someone successfully `FLEE`s (chance scales with Evasion;
failing gives the opponent a free swing). Other commands (training,
travelling, equipping) are blocked while you're in combat.

**Equipment** (`EQUIP <item>` / `UNEQUIP`) lets you wield a weapon from
your inventory; each weapon has a damage type (melee/ranged/magic) and
attribute bonuses (see `game/items.py`) that feed directly into your
combat profile. Unarmed, everyone fights weak melee with their bare
Strength -- getting a weapon (e.g. from a quest reward) is a real power
spike.

PvP is **mutual, staked duels only** -- no unsolicited ganking:
`DUEL CHALLENGE <user>`, then both sides `DUEL STAKE FIAT|XBT|ITEM|
COMPANION ...`, and the challenged player `DUEL ACCEPT` to kick off the
real-time fight; the winner takes the loser's stake.

### Quests
Declarative in `game/quests.py`: an id, a `check(username)` predicate
re-evaluated against live player state, and a reward (fiat/items/
companion). The tutorial quest ("Journey to Town") auto-starts on
registration and completes the moment you arrive. New quests are just new
entries -- the engine re-checks all of a player's active quests after
every command.

Quests can also offer a **choice of item reward** (`reward_choice`): fiat
and companion rewards are granted immediately, but the quest parks in an
"awaiting_choice" state until you run `CHOOSE <option>`. "Journey to
Town" offers a magic staff, wooden bow, or bronze sword -- whichever you
pick is automatically equipped.

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
game/travel.py          TRAVEL command resolution (delayed, ETA-based)
game/resource_nodes.py  Shared depletable resource node catalog (iron/gold veins)
game/chat.py             Ephemeral, in-memory location-scoped chat (never persisted)
game/mapview.py          ASCII overworld map renderer
game/companions.py     Companion species catalog
game/monsters.py       Wild monster catalog
game/skills/attributes.py  STR/DEX/CON/EVASION/INT combat-attribute skills
game/combat_stats.py    HP/mana regen + combat profile derivation (attributes+weapon+companion)
game/stakes.py          Duel stake validation/transfer helpers
game/battle.py          Real-time diku-style auto-attack combat engine (PvE/PvP/flee)
game/combat.py          Duel admin (challenge/stake/accept/cancel) + buy_companion
game/equipment.py       EQUIP/UNEQUIP weapon commands
game/quests.py          Quest framework & definitions (incl. reward-choice quests)
game/ui.py              ANSI dashboard screens
tests/                 Unit tests (economy, skills, world, quests, combat, duels)
```

## Tests

```
python3 -m unittest discover -s tests
```
