#!/usr/bin/env python3
"""Minimal CDP evaluate: prints location, title and a slice of body text for a URL match."""
import asyncio
import json
import sys
import urllib.request

import websockets


def targets():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=10) as r:
        return json.loads(r.read())


async def ev(ws_url, expr):
    async with websockets.connect(ws_url, max_size=20_000_000) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": expr, "returnByValue": True}}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                return msg.get("result", {}).get("result", {}).get("value")


def main():
    needle = sys.argv[1] if len(sys.argv) > 1 else "facebook.com"
    expr = sys.argv[2] if len(sys.argv) > 2 else "location.href + '\\n' + document.title + '\\n' + (document.body ? document.body.innerText.slice(0,400) : '')"
    for t in targets():
        if needle in (t.get("url") or ""):
            print("target:", t.get("url")[:90])
            print(asyncio.run(ev(t["webSocketDebuggerUrl"], expr)))
            return
    print("no target matching", needle)


if __name__ == "__main__":
    main()
