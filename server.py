"""We're F'd: An XBT MMO -- TCP server.

A line-based, telnet-friendly protocol: connect with `nc host port` or any
raw TCP client, type commands, read responses. ANSI screens (DASHBOARD,
SKILLS, INVENTORY, QUESTS, COMPANIONS, MAP) redraw cleanly in any terminal
emulator without needing curses or a dedicated client.
"""
from __future__ import annotations

import asyncio
import logging

from game import battle, chat, combat, companions, config, db, economy, equipment, quests, training, travel, ui, world
import game.skills  # noqa: F401  (import registers FISHING/MINING/COOKING)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("werefd")

# Serializes all economy/db mutations so a single-process server never races
# itself across concurrent client coroutines.
GAME_LOCK = asyncio.Lock()
ONLINE_USERS: set[str] = set()
SESSIONS: dict[str, "Session"] = {}

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
-- Screens (redrawn ANSI panels) --
  DASHBOARD                 Overview: location, balances, skills, quests
  SKILLS                    Detailed skill levels & unlockable actions
  INVENTORY                 Your items
  QUESTS                    Quest log
  COMPANIONS                Your companions
  MAP                       World map / current location

-- Economy --
  STATUS                    Your balances, hash power, and cooldowns
  BUY HASH <n>              Buy n GH/s of XBT-Hash ($%.2f/GH/s, draws %.1fW each)
  MARKET PRICE              Current XBT price in fiat
  MARKET BUY <fiat>         Spend fiat to buy XBT
  MARKET SELL <xbt>         Sell XBT for fiat
  FIGHT GOBLIN | DRAGON     Risk a fiat stake against the shared pool
  QUEST                     Free, guaranteed small pool payout (cooldown)

-- World & skilling --
  TRAVEL <direction>        Set off toward a connected location (takes time -- see MAP)
  TRAIN <skill> <action>    Train a skill action, e.g. TRAIN FISHING SHRIMP
  SAY <message>             Chat to players in your current location (fades after 60s)
  BUY COMPANION <species>   Buy a companion with XBT (shop species only)

-- Combat --
  PVE <monster>             Engage a wild monster -- auto-attack starts, rounds push live
  DUEL CHALLENGE <user>     Challenge another player to a staked duel
  DUEL STAKE FIAT <amount> | XBT <amount> | ITEM <id> <qty> | COMPANION <id>
  DUEL ACCEPT               Accept your pending duel -- auto-attack begins
  DUEL CANCEL               Cancel your pending duel
  DUEL STATUS               Show your pending duel
  FLEE                      Attempt to disengage from your current fight
  EQUIP <item>              Equip a weapon from your inventory
  UNEQUIP                   Unequip your current weapon
  CHOOSE <option>           Pick an awaiting quest reward, e.g. CHOOSE SWORD

  QUIT                      Disconnect
""" % (
    config.HASH_PRICE_FIAT,
    config.WATTS_PER_GHS,
)


class Session:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.username: str | None = None
        self.last_event: str = ""
        self.location: str | None = None
        self.auto_dashboard: bool = False

    async def send(self, text: str):
        if not text.startswith("\x1b[2J"):  # don't let full-screen redraws clobber last_event
            self.last_event = text.replace("\n", " ").strip()[:120]
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
            if self.username:
                ONLINE_USERS.discard(self.username)
                SESSIONS.pop(self.username, None)
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

        # DASHBOARD auto-refreshes every 10s (see dashboard_refresh_loop) until
        # any other command is run, so it doesn't clobber other screens.
        self.auto_dashboard = verb == "DASHBOARD"

        # Lazily finalize any completed trip before this command runs, and
        # keep our cached location in sync (used for same-room presence/chat).
        self.location = await asyncio.to_thread(travel.resolve_arrival, self.username)

        if verb == "STATUS":
            await self.cmd_status()
        elif verb == "DASHBOARD":
            await self.send(await asyncio.to_thread(
                ui.dashboard, self.username, self.last_event, len(ONLINE_USERS), self.players_here()
            ))
        elif verb == "SKILLS":
            await self.send(await asyncio.to_thread(ui.skills_screen, self.username))
        elif verb == "INVENTORY":
            await self.send(await asyncio.to_thread(ui.inventory_screen, self.username))
        elif verb == "QUESTS":
            await self.send(await asyncio.to_thread(ui.quests_screen, self.username))
        elif verb == "COMPANIONS":
            await self.send(await asyncio.to_thread(ui.companions_screen, self.username))
        elif verb == "MAP":
            await self.send(await asyncio.to_thread(ui.map_screen, self.username, self.players_here()))
        elif verb in ("TRAVEL", "GO") and len(parts) == 2:
            await self.cmd_travel(parts[1])
        elif verb == "TRAIN" and len(parts) == 3:
            await self.cmd_train(parts[1], parts[2])
        elif verb == "SAY" and len(parts) >= 2:
            await self.cmd_say(cmd.split(" ", 1)[1])
        elif verb == "BUY" and len(parts) >= 3 and parts[1].upper() == "HASH":
            await self.cmd_buy_hash(parts)
        elif verb == "BUY" and len(parts) == 3 and parts[1].upper() == "COMPANION":
            await self.cmd_buy_companion(parts[2])
        elif verb == "SET" and len(parts) == 3 and parts[1].upper() == "COMPANION":
            await self.cmd_set_companion(parts[2])
        elif verb == "MARKET":
            await self.cmd_market(parts)
        elif verb == "PVE" and len(parts) == 2:
            await self.cmd_pve(parts[1])
        elif verb == "DUEL":
            await self.cmd_duel(parts)
        elif verb == "FLEE":
            await self.cmd_flee()
        elif verb == "EQUIP" and len(parts) == 2:
            await self.cmd_equip(parts[1])
        elif verb == "UNEQUIP":
            await self.cmd_unequip()
        elif verb == "CHOOSE" and len(parts) == 2:
            await self.cmd_choose(parts[1])
        elif verb == "FIGHT" and len(parts) >= 2:
            await self.cmd_action(parts[1])
        elif verb == "QUEST":
            await self.cmd_action("QUEST")
        else:
            await self.send("ERR unknown command. Type HELP.")

        await self.check_quests()
        return True

    def players_here(self) -> list[str]:
        return [name for name, sess in SESSIONS.items() if sess.location == self.location]

    async def cmd_say(self, message: str):
        message = message.strip()
        if not message:
            await self.send("ERR usage: SAY <message>")
            return
        player = await asyncio.to_thread(db.get_player, self.username)
        travelling, remaining = travel.is_travelling(player)
        if travelling:
            await self.send(f"ERR you're on the road, no one to talk to. Arriving in {remaining:.0f}s.")
            return
        await asyncio.to_thread(chat.post, self.location, self.username, message)
        for sess in SESSIONS.values():
            if sess.location == self.location:
                await sess.send(f"OK [{self.username}] {message}")

    async def check_quests(self):
        messages = await asyncio.to_thread(quests.check_and_complete, self.username)
        for msg in messages:
            await self.send("OK " + msg)

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
            await asyncio.to_thread(quests.start_default_quests, username)
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
        self.location = (await asyncio.to_thread(db.get_player, username)).location
        ONLINE_USERS.add(username)
        SESSIONS[username] = self
        await self.send(f"OK welcome back, {username}. Type DASHBOARD or HELP for commands.")

    async def cmd_status(self):
        player = await asyncio.to_thread(db.get_player, self.username)
        price = await asyncio.to_thread(economy.amm_price)
        await self.send(
            f"OK user={player.username} fiat=${player.fiat:,.2f} xbt={player.xbt:.8f} "
            f"hash={player.hash_power_ghs:g}GH/s xbt_price=${price:,.2f} location={player.location}"
        )

    async def cmd_travel(self, direction: str):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(travel.travel, self.username, direction)
        self.location = (await asyncio.to_thread(db.get_player, self.username)).location
        await self.send(("OK\n" if ok else "ERR ") + msg)

    async def cmd_train(self, skill_id: str, action_id: str):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(training.train, self.username, skill_id, action_id)
        await self.send(("OK " if ok else "ERR ") + msg)

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

    async def cmd_buy_companion(self, species_id: str):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(combat.buy_companion, self.username, species_id)
        await self.send(("OK " if ok else "ERR ") + msg)

    async def cmd_set_companion(self, companion_id_str: str):
        try:
            companion_id = int(companion_id_str)
        except ValueError:
            await self.send("ERR usage: SET COMPANION <id>")
            return
        comp = await asyncio.to_thread(db.get_companion, companion_id)
        if comp is None or comp["username"] != self.username:
            await self.send("ERR you don't own that companion.")
            return
        await asyncio.to_thread(db.set_active_companion, self.username, companion_id)
        await self.send(f"OK {comp['nickname']} is now your active companion.")

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

    async def cmd_pve(self, monster_id: str):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(battle.start_pve, self.username, monster_id)
        await self.send(("OK\n" if ok else "ERR ") + msg)

    async def cmd_flee(self):
        async with GAME_LOCK:
            ok, msg, pushes = await asyncio.to_thread(battle.flee, self.username)
            for target_user, push_msg in pushes:
                sess = SESSIONS.get(target_user)
                if sess is not None:
                    await sess.send("OK " + push_msg)
        await self.send(("OK " if ok else "ERR ") + msg)

    async def cmd_equip(self, item_id: str):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(equipment.equip, self.username, item_id)
        await self.send(("OK " if ok else "ERR ") + msg)

    async def cmd_unequip(self):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(equipment.unequip, self.username)
        await self.send(("OK " if ok else "ERR ") + msg)

    async def cmd_choose(self, option: str):
        async with GAME_LOCK:
            ok, msg = await asyncio.to_thread(quests.choose_reward, self.username, option)
        await self.send(("OK " if ok else "ERR ") + msg)

    async def cmd_duel(self, parts: list[str]):
        if len(parts) < 2:
            await self.send("ERR usage: DUEL CHALLENGE|STAKE|ACCEPT|CANCEL|STATUS ...")
            return
        sub = parts[1].upper()

        if sub == "CHALLENGE" and len(parts) == 3:
            async with GAME_LOCK:
                ok, msg = await asyncio.to_thread(combat.challenge, self.username, parts[2])
            await self.send(("OK " if ok else "ERR ") + msg)
            return

        if sub == "STATUS":
            duel = await asyncio.to_thread(db.get_pending_duel_for, self.username)
            if duel is None:
                await self.send("OK no pending duel.")
            else:
                await self.send(
                    f"OK duel #{duel['id']} {duel['challenger']} vs {duel['target']} "
                    f"status={duel['status']} challenger_stake={duel['challenger_stake']} "
                    f"target_stake={duel['target_stake']}"
                )
            return

        duel = await asyncio.to_thread(db.get_pending_duel_for, self.username)
        if duel is None:
            await self.send("ERR no pending duel. Start one with DUEL CHALLENGE <user>.")
            return

        if sub == "STAKE" and len(parts) >= 4:
            stake_type = parts[2].lower()
            stake = None
            try:
                if stake_type == "fiat":
                    stake = {"type": "fiat", "amount": float(parts[3])}
                elif stake_type == "xbt":
                    stake = {"type": "xbt", "amount": float(parts[3])}
                elif stake_type == "item" and len(parts) == 5:
                    stake = {"type": "item", "item_id": parts[3].lower(), "qty": int(parts[4])}
                elif stake_type == "companion":
                    stake = {"type": "companion", "companion_id": int(parts[3])}
            except ValueError:
                stake = None
            if stake is None:
                await self.send("ERR usage: DUEL STAKE FIAT <amount> | XBT <amount> | ITEM <id> <qty> | COMPANION <id>")
                return
            async with GAME_LOCK:
                ok, msg = await asyncio.to_thread(combat.set_stake, self.username, duel["id"], stake)
            await self.send(("OK " if ok else "ERR ") + msg)
            return

        if sub == "ACCEPT":
            async with GAME_LOCK:
                ok, msg = await asyncio.to_thread(combat.accept, duel["id"], self.username)
            if ok:
                challenger_sess = SESSIONS.get(duel["challenger"])
                if challenger_sess is not None and challenger_sess is not self:
                    await challenger_sess.send("OK\n" + msg)
            await self.send(("OK\n" if ok else "ERR ") + msg)
            return

        if sub == "CANCEL":
            async with GAME_LOCK:
                ok, msg = await asyncio.to_thread(combat.cancel, duel["id"], self.username)
            await self.send(("OK " if ok else "ERR ") + msg)
            return

        await self.send("ERR usage: DUEL CHALLENGE|STAKE|ACCEPT|CANCEL|STATUS ...")

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


async def dashboard_refresh_loop():
    """Re-pushes the DASHBOARD screen every DASHBOARD_REFRESH_SECONDS to any
    session currently viewing it, so balances/timers update without the
    player needing to retype DASHBOARD. Stops the moment they run any other
    command (see Session.dispatch)."""
    while True:
        await asyncio.sleep(config.DASHBOARD_REFRESH_SECONDS)
        for sess in list(SESSIONS.values()):
            if not sess.auto_dashboard or sess.username is None:
                continue
            try:
                text = await asyncio.to_thread(
                    ui.dashboard, sess.username, sess.last_event, len(ONLINE_USERS), sess.players_here()
                )
                await sess.send(text)
            except Exception:
                log.exception("error auto-refreshing dashboard for %s", sess.username)


async def combat_round_loop():
    """Advances every active real-time battle each pulse and pushes any new
    round lines straight to the fighters' terminals, independent of
    whatever command they're otherwise typing -- the diku-style auto-attack
    engine runs on its own clock."""
    while True:
        await asyncio.sleep(config.COMBAT_PULSE_SECONDS)
        async with GAME_LOCK:
            pushes = await asyncio.to_thread(battle.process_tick)
        for username, msg in pushes:
            sess = SESSIONS.get(username)
            if sess is not None:
                try:
                    await sess.send("OK " + msg)
                except Exception:
                    log.exception("error pushing combat update to %s", username)



async def handle_client(reader, writer):
    await Session(reader, writer).handle()


async def main():
    await asyncio.to_thread(db.init_db)
    asyncio.create_task(tick_loop())
    asyncio.create_task(dashboard_refresh_loop())
    asyncio.create_task(combat_round_loop())
    server = await asyncio.start_server(handle_client, config.HOST, config.PORT)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    log.info("serving on %s", addrs)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
