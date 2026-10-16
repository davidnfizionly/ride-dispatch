"""Records the WebSocket feed of the local stack while one ride runs, for the
UI replay mode (ui/public/replay.json). Positions snapshots are kept once per
second; every lifecycle event is kept.

Environment: WS_URL, WS_TOKEN. Usage: python scripts/record_feed.py OUT_PATH
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect


async def main(out):
    url = f"{os.environ['WS_URL']}?token={os.environ['WS_TOKEN']}"
    records, t0, sent, ride_id = [], time.monotonic(), False, None
    async with connect(url, max_size=2**20) as ws:
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            t = int((time.monotonic() - t0) * 1000)
            if msg.get("type") == "requestAck":
                ride_id = msg.get("ride_id")
            records.append({"t": t, "msg": msg})
            if not sent and t > 4000:
                await ws.send(json.dumps({"action": "requestRide", "client_id": "C1",
                                          "pickup": {"lat": -1.2864, "lng": 36.8172},
                                          "dropoff": {"lat": -1.2676, "lng": 36.8108}}))
                sent = True
            if msg.get("type") == "TripCompleted" and msg["detail"].get("ride_id") == ride_id:
                break
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(records, f, separators=(",", ":"))
    print(f"recorded {len(records)} messages over {records[-1]['t'] / 1000:.0f} s to {out}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
