"""Minimal interactive terminal client for We're F'd: An XBT MMO.

A raw `nc host port` or `telnet host port` works fine too -- this just
adds a prompt and reads server pushes without you needing to manage
the socket yourself.

Usage: python client.py [host] [port]
"""
import asyncio
import sys


async def pump_output(reader: asyncio.StreamReader):
    while True:
        line = await reader.readline()
        if not line:
            print("\n[disconnected]")
            return
        print(line.decode(errors="ignore").rstrip())


async def pump_input(writer: asyncio.StreamWriter):
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        writer.write(line.encode())
        await writer.drain()
        if line.strip().upper() == "QUIT":
            break


async def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6565
    reader, writer = await asyncio.open_connection(host, port)
    out_task = asyncio.create_task(pump_output(reader))
    try:
        await pump_input(writer)
    finally:
        out_task.cancel()
        writer.close()


if __name__ == "__main__":
    asyncio.run(main())
