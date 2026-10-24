"""Expose SignalRGB's WebPipe (127.0.0.1:16036) to selected LAN hosts.

SignalRGB only binds its WebPipe QWebChannel to localhost. This forwards raw
TCP from a LAN port to it, accepting connections only from the listed client
IPs (the channel carries account details and full app control).

    pythonw webpipe_relay.py --allow 192.168.1.10
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

TARGET = ("127.0.0.1", 16036)
LOG_FILE = Path(__file__).with_suffix(".log")

log = logging.getLogger("webpipe_relay")


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except ConnectionError, asyncio.CancelledError:
        pass
    finally:
        writer.close()


def make_handler(allowed: set[str]):
    async def handle(
        client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        peer = client_writer.get_extra_info("peername")[0]
        if peer.startswith("::ffff:"):
            peer = peer[7:]
        if peer not in allowed:
            log.warning("rejected %s", peer)
            client_writer.close()
            return
        try:
            target_reader, target_writer = await asyncio.open_connection(*TARGET)
        except OSError as err:
            log.warning("cannot reach SignalRGB WebPipe for %s: %s", peer, err)
            client_writer.close()
            return
        log.info("relaying %s", peer)
        await asyncio.gather(pipe(client_reader, target_writer), pipe(target_reader, client_writer))
        log.info("closed %s", peer)

    return handle


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--allow", action="append", required=True, help="client IP allowed to connect (repeatable)"
    )
    parser.add_argument(
        "--port", type=int, default=16046, help="LAN port to listen on (default 16046)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    server = await asyncio.start_server(
        make_handler(set(args.allow)),
        host="0.0.0.0",  # noqa: S104 - LAN relay; peers are filtered by --allow
        port=args.port,
    )
    log.info("listening on 0.0.0.0:%s, allowing %s", args.port, ", ".join(args.allow))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
