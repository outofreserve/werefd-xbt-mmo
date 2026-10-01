"""We're F'd: An XBT MMO -- TCP server.

A line-based, telnet-friendly protocol: connect with `nc host port` or any
raw TCP client, type commands, read responses. No client required, though
client.py provides a nicer prompt-based wrapper.
"""
from __future__ import annotations

import asyncio
import logging
import time

from game import config, db, economy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("werefd")

# Serializes all economy/db mutations so a single-process server never races
# itself across concurrent client coroutines.
GAME_LOCK = asyncio.Lock()

WELCOME = """\
==================================================
 WE'RE F'D: AN XBT MMO
==================================================
Commands:
  REGISTER <user> <pass>   Create an account (password can NEVER be recovered -- write it down!)
  LOGIN <user> <pass>      Log in
  HELP                     Show this again
  QUIT                     Disconnect

Type a command and press enter.
"""

HELP_TEXT = """\
Commands:
  STATUS                   Your balances, hash power, and cooldowns
  BUY HASH <n>             Buy n GH/s of XBT-Hash ($%.2f/GH/s, draws %.1fW each)
  MARKET PRICE             Current XBT price in fiat
  MARKET BUY <fiat>        Spend fiat to buy XBT
  MARKET SELL <xbt>        Sell XBT for fiat
  FIGHT GOBLIN             Cost $%.2f, %.0f%% win chance, reward $%.2f
  FIGHT DRAGON             Cost $%.2f, %.0f%% win chance, reward $%.2f
  QUEST                    Free, guaranteed small reward (cooldown %ds)
  QUIT                     Disconnect
""" % (
    config.HASH_PRICE_FIAT,
    config.WATTS_PER_GHS,
    config.ACTIONS["GOBLIN"]["cost"], config.ACTIONS["GOBLIN"]["win_chance"] * 100, config.ACTIONS["GOBLIN"]["reward"],
    config.ACTIONS["DRAGON"]["cost"], config.ACTIONS["DRAGON"]["win_chance"] * 100, config.ACTIONS["DRAGON"]["reward"],
    config.ACTIONS["QUEST"]["cooldown"],
)


class Session:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.username: str | None = None

    async def send(self, text: str):
        self.writer.write((text + "\n").encode())
        await self.writer.drain()

    async def handle(self):
        peer = self.writer.get_extra_info("peername")
        log.info("connection from %s", peer)
        await self.send(WELCOME)
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break
                cmd = line.decode(errors="ignore").strip()
                if not cmd:
                    continue
                try:
                    should_continue = await self.dispatch(cmd)
                except Exception as exc:  # keep the connection alive on bad input
                    log.exception("error handling command %r", cmd)
                    await self.send(f"ERR internal error: {exc}")
                    should_continue = True
                if not should_continue:
                    break
        finally:
            log.info("connection closed %s (user=%s)", peer, self.username)
            self.writer.close()

    async def dispatch(self, cmd: str) -> bool:
        parts = cmd.split()
        verb = parts[0].upper()

        if verb == "QUIT":
            await self.send("OK bye.")
            return False
        if verb == "HELP":
            await self.send(HELP_TEXT)
            return True
        if verb == "REGISTER":
            await self.cmd_register(parts)
            return True
        if verb == "LOGIN":
            await self.cmd_login(parts)
            return True

        if self.username is None:
            await self.send("ERR please LOGIN or REGISTER first.")
            return True

        if verb == "STATUS":
            await self.cmd_status()
        elif verb == "BUY" and len(parts) >= 3 and parts[1].upper() == "HASH":
            await self.cmd_buy_hash(parts)
        elif verb == "MARKET":
            await self.cmd_market(parts)
        elif verb == "FIGHT" and len(parts) >= 2:
            await self.cmd_action(parts[1])
        elif verb == "QUEST":
            await self.cmd_action("QUEST")
        else:
            await self.send("ERR unknown command. Type HELP.")
        return True

    async def cmd_register(self, parts: list[str]):
        if len(parts) != 3:
            await self.send("ERR usage: REGISTER <user> <pass>")
            return
        username, password = parts[1], parts[2]
        if len(password) < config.MIN_PASSWORD_LEN:
            await self.send(f"ERR password must be at least {config.MIN_PASSWORD_LEN} characters.")
            return
        async with GAME_LOCK:
            try:
                await asyncio.to_thread(db.create_player, username, password)
            except ValueError as exc:
                await self.send(f"ERR {exc}")
                return
        await self.send(
            f"OK account '{username}' created with ${config.STARTING_FIAT:,.2f}. "
            "WRITE YOUR PASSWORD DOWN -- it cannot ever be recovered. Now LOGIN."
        )

    async def cmd_login(self, parts: list[str]):
        if len(parts) != 3:
            await self.send("ERR usage: LOGIN <user> <pass>")
            return
        username, password = parts[1], parts[2]
        ok = await asyncio.to_thread(db.authenticate, username, password)
        if not ok:
            await self.send("ERR invalid username or password.")
            return
        self.username = username
        await self.send(f"OK welcome back, {username}. Type HELP for commands.")

    async def cmd_status(self):
        player = await asyncio.to_thread(db.get_player, self.username)
        price = await asyncio.to_thread(economy.amm_price)
        await self.send(
            f"OK user={player.username} fiat=${player.fiat:,.2f} xbt={player.xbt:.8f} "
            f"hash={player.hash_power_ghs:g}GH/s xbt_price=${price:,.2f}"
        )

    async def cmd_buy_hash(self, parts: list[str]):
        try:
            units = float(parts[2])
            assert units > 0
        except (ValueError, AssertionError):
            await self.send("ERR usage: BUY HASH <positive number>")
            return
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(economy.buy_hash, self.username, units)
        await self.send(("OK " if ok else "ERR ") + msg)

    async def cmd_market(self, parts: list[str]):
        if len(parts) < 2:
            await self.send("ERR usage: MARKET PRICE | MARKET BUY <fiat> | MARKET SELL <xbt>")
            return
        sub = parts[1].upper()
        if sub == "PRICE":
            price = await asyncio.to_thread(economy.amm_price)
            await self.send(f"OK xbt_price=${price:,.2f}")
            return
        if sub in ("BUY", "SELL") and len(parts) == 3:
            try:
                amount = float(parts[2])
            except ValueError:
                await self.send("ERR amount must be a number.")
                return
            async with GAME_LOCK:
                if sub == "BUY":
                    ok, msg = await asyncio.to_thread(economy.market_buy, self.username, amount)
                else:
                    ok, msg = await asyncio.to_thread(economy.market_sell, self.username, amount)
            await self.send(("OK " if ok else "ERR ") + msg)
            return
        await self.send("ERR usage: MARKET PRICE | MARKET BUY <fiat> | MARKET SELL <xbt>")

    async def cmd_action(self, action_name: str):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(economy.do_action, self.username, action_name)
        await self.send(("OK " if ok else "ERR ") + msg)


async def tick_loop():
    while True:
        await asyncio.sleep(config.TICK_SECONDS)
        async with GAME_LOCK:
            summary = await asyncio.to_thread(economy.tick)
        if summary["block_paid"]:
            log.info("block reward paid out")


async def handle_client(reader, writer):
    await Session(reader, writer).handle()


async def main():
    await asyncio.to_thread(db.init_db)
    asyncio.create_task(tick_loop())
    server = await asyncio.start_server(handle_client, config.HOST, config.PORT)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    log.info("serving on %s", addrs)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
