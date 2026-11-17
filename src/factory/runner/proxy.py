"""Egress proxy: the only way out of an agent's network. HTTPS CONNECT to allowlisted hosts only.

Runs as its own container, attached to the run's internal network and to an outbound network.
An allowlist entry `example.com` allows that exact host; `.example.com` allows its subdomains too.
"""

import argparse
import asyncio
import sys

ALLOWED_PORTS = frozenset({443})
MAX_HEAD = 8192


def allowed(
    host: str, port: int, allowlist: list[str], ports: frozenset[int] = ALLOWED_PORTS
) -> bool:
    host = host.lower().rstrip(".")
    if port not in ports:
        return False
    for entry in allowlist:
        entry = entry.lower()
        if entry.startswith("."):
            if host == entry[1:] or host.endswith(entry):
                return True
        elif host == entry:
            return True
    return False


def parse_connect(head: bytes) -> tuple[str, int] | None:
    """Target of a `CONNECT host:port HTTP/1.1` request line, or None for anything else."""
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "CONNECT":
        return None
    host, _, port = parts[1].rpartition(":")
    if not host or not port.isdigit():
        return None
    return host.strip("[]"), int(port)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def _handle(
    allowlist: list[str],
    ports: frozenset[int],
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        writer.close()
        return
    target = parse_connect(head)
    if target is None or not allowed(*target, allowlist, ports):
        log(f"deny {target[0]}:{target[1]}" if target else "deny non-CONNECT request")
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        return
    host, port = target
    try:
        up_reader, up_writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=30
        )
    except (OSError, TimeoutError) as exc:
        log(f"fail  {host}:{port} {exc}")
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        return
    log(f"allow {host}:{port}")
    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))


async def start(
    allowlist: list[str], host: str, port: int, ports: frozenset[int] = ALLOWED_PORTS
) -> asyncio.Server:
    server = await asyncio.start_server(
        lambda r, w: _handle(allowlist, ports, r, w), host, port, limit=MAX_HEAD
    )
    log(f"egress proxy on {host}:{port}, allowing {', '.join(allowlist)}")
    return server


async def serve(allowlist: list[str], host: str, port: int) -> None:
    async with await start(allowlist, host, port) as server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factory-egress")
    parser.add_argument("--allow", required=True, help="comma-separated hosts")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container-internal listener
    parser.add_argument("--port", type=int, default=3128)
    args = parser.parse_args(argv)
    allowlist = [h.strip() for h in args.allow.split(",") if h.strip()]
    asyncio.run(serve(allowlist, args.host, args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
