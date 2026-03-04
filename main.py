#!/usr/bin/env python3
"""
WebSocket Tunnel Server for Render.com
Uses websockets library for proper protocol handling
(ping/pong, fragmentation, continuation frames all handled automatically)
"""

import asyncio
import os
import websockets
from http import HTTPStatus

PORT = int(os.environ.get("PORT", 10000))
BUFFER_SIZE = 65536


async def process_request(path, request_headers):
    """Handle HTTP health checks (non-WebSocket requests)"""
    if path == "/" or path == "/health":
        return HTTPStatus.OK, [], b"OK\n"


async def handler(websocket, path):
    """Handle WebSocket tunnel connections"""
    parts = path.strip("/").split("/")

    if len(parts) < 3 or parts[0] != "tunnel":
        await websocket.close(1002, "Invalid path")
        return

    host = parts[1]
    port = int(parts[2])

    print(f"  [>] Target: {host}:{port}", flush=True)

    try:
        reader, writer = await asyncio.open_connection(host, port)
        print(f"  [✓] Connected to {host}:{port}", flush=True)
    except Exception as e:
        print(f"  [!] Connect failed: {e}", flush=True)
        return

    ws_to_tcp_total = 0
    tcp_to_ws_total = 0

    async def ws_to_tcp():
        nonlocal ws_to_tcp_total
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    writer.write(message)
                    await writer.drain()
                    ws_to_tcp_total += len(message)
                elif isinstance(message, str):
                    # Text frame - encode and forward
                    data = message.encode('utf-8')
                    writer.write(data)
                    await writer.drain()
                    ws_to_tcp_total += len(data)
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            print(f"      [ws→tcp err] {e}", flush=True)
        finally:
            try:
                writer.close()
            except:
                pass
            print(f"      [ws→tcp] {ws_to_tcp_total} bytes", flush=True)

    async def tcp_to_ws():
        nonlocal tcp_to_ws_total
        try:
            while True:
                data = await reader.read(BUFFER_SIZE)
                if not data:
                    break
                await websocket.send(data)
                tcp_to_ws_total += len(data)
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            print(f"      [tcp→ws err] {e}", flush=True)
        finally:
            print(f"      [tcp→ws] {tcp_to_ws_total} bytes", flush=True)

    tasks = [
        asyncio.create_task(ws_to_tcp()),
        asyncio.create_task(tcp_to_ws()),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def main():
    async with websockets.serve(
        handler,
        "0.0.0.0",
        PORT,
        process_request=process_request,
        max_size=None,
        ping_interval=20,
        ping_timeout=20,
        compression=None,
    ):
        print(f"🚀 WebSocket Tunnel Server running on port {PORT}", flush=True)
        print("Press Ctrl+C to stop...", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
