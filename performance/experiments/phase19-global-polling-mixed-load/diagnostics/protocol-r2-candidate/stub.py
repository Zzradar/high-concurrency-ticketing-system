"""Generator qualification only: same wire shape, parser and shared VU fixture as SUT reads."""
import asyncio
import json
from urllib.parse import urlsplit, parse_qs


def response(target):
    path = urlsplit(target)
    query = parse_qs(path.query)
    zone = query.get("zone", ["Zone 0"])[0]
    snapshot = "since" not in query
    body = {"sessionId": path.path.split("/")[2], "zone": zone, "mode": "snapshot" if snapshot else "delta",
            "generation": "phase19-generator", "cursor": "1-0", "reset": False, "degraded": False,
            "hasMore": False, "pollAfterMs": 2000 if snapshot else 5000,
            "zones": [{"zone": "Zone " + str(i), "total": 1000, "available": 1000, "held": 0, "sold": 0} for i in range(5)]}
    body["seats" if snapshot else "changes"] = [{"id": "phase19-seat-" + str(i), "status": "AVAILABLE"} for i in range(1000)] if snapshot else []
    return json.dumps(body, separators=(",", ":")).encode()


async def connection(reader, writer):
    try:
        while True:
            header = await reader.readuntil(b"\r\n\r\n")
            method, target, version = header.split(b"\r\n", 1)[0].decode().split()
            if method != "GET":
                break
            raw = response(target)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.LimitOverrunError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    server = await asyncio.start_server(connection, "0.0.0.0", 8080)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
