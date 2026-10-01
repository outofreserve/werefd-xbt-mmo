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
| `STATUS` | Fiat balance, XBT balance, hash power, XBT price |
| `BUY HASH <n>` | Buy `n` GH/s of XBT-Hash hardware |
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

## Project layout

```
server.py        Entry point: TCP server, protocol, connection handling
client.py         Optional thin terminal client
game/config.py    All tunable constants
game/db.py        SQLite schema & accessors
game/economy.py   Interest, electricity billing, mining, AMM, actions
tests/            Unit tests for the economy math
```

## Tests

```
python3 -m unittest discover -s tests
```
