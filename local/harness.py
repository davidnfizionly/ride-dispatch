"""Local stand-in for the AWS wiring, so the real handlers run offline.

  EventBridge rules: LocalBus dispatching to the same handler functions
  MSK event source mappings: two Kafka consumer groups ("matching", "archiver")
    feeding MSK-shaped batches to the handlers
  API Gateway WebSocket: a websockets server on port 8765
  DynamoDB: in-memory stores
  S3: local/data/archive

The handler modules are the ones deployed to Lambda; only the wiring differs.
"""
import asyncio
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import redis
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from archiver import handlers as archiver
from lifecycle import handlers as lifecycle
from lifecycle.stores import MemoryConnectionStore, MemoryRideStore
from matching import handlers as matching
from matching.driver_index import DriverIndex
from matching.geo import zone_of
from matching.osrm_client import OsrmClient
from shared import events
from shared.kafka_io import make_consumer, make_producer

TOKEN = os.environ.get("CONNECT_TOKEN", "local-dev-token")
ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR", "/w/local/data/archive")


def log(**kw):
    print(json.dumps({"t": round(time.time(), 3), **kw}), flush=True)


class LocalBus:
    """Emulates the EventBridge rules: async fan-out of each event to its targets."""

    def __init__(self):
        self.rules = []
        self._pool = ThreadPoolExecutor(max_workers=8)

    def rule(self, detail_types, target):
        self.rules.append((set(detail_types), target))

    def put(self, detail_type, detail):
        event = {"source": events.SOURCE, "detail-type": detail_type, "detail": detail}
        for types, target in self.rules:
            if detail_type in types:
                self._pool.submit(self._invoke, target, event)

    @staticmethod
    def _invoke(target, event):
        try:
            result = target(event)
            if event["detail-type"] != events.POSITIONS_SNAPSHOT:
                log(rule_target=target.__name__, detail_type=event["detail-type"], result=result)
        except Exception as e:  # noqa: BLE001 - keep the harness alive, report the failure
            log(rule_target=target.__name__, error=repr(e))


class WebSocketGateway:
    def __init__(self, deps):
        self.deps = deps
        self.loop = None
        self.conns = {}

    def post(self, connection_id, data):
        ws = self.conns.get(connection_id)
        if ws is None:
            raise lifecycle.GoneConnection(connection_id)
        fut = asyncio.run_coroutine_threadsafe(ws.send(data.decode()), self.loop)
        try:
            fut.result(timeout=2)
        except (ConnectionClosed, TimeoutError) as e:
            raise lifecycle.GoneConnection(connection_id) from e

    async def handler(self, ws):
        cid = uuid.uuid4().hex[:12]
        query = {k: v[0] for k, v in parse_qs(urlparse(ws.request.path).query).items()}
        ctx = {"requestContext": {"connectionId": cid}, "queryStringParameters": query}
        if lifecycle.handle_connect(ctx, self.deps)["statusCode"] != 200:
            await ws.close(code=4401, reason="unauthorized")
            return
        self.conns[cid] = ws
        log(ws="connect", connection_id=cid)
        try:
            async for message in ws:
                body = json.loads(message)
                if body.get("action") == "requestRide":
                    resp = await asyncio.to_thread(
                        lifecycle.handle_request, {**ctx, "body": message}, self.deps)
                    await ws.send(resp["body"])
        except ConnectionClosed:
            pass
        finally:
            self.conns.pop(cid, None)
            lifecycle.handle_disconnect(ctx, self.deps)
            log(ws="disconnect", connection_id=cid)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        async with serve(self.handler, "0.0.0.0", 8765):
            log(ws="listening", port=8765)
            await asyncio.Future()


def consume_batches(group, topic, handler, batch_window_ms):
    """Emulates an MSK event source mapping: polls a batch, invokes, commits."""
    consumer = make_consumer([topic], group, enable_auto_commit=False)
    while True:
        polled = consumer.poll(timeout_ms=batch_window_ms, max_records=500)
        values = [r.value for records in polled.values() for r in records]
        if not values:
            continue
        try:
            handler(events.encode_msk_event(values, topic=topic))
            consumer.commit()
        except Exception as e:  # noqa: BLE001
            log(group=group, error=repr(e))


def main():
    r = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379)
    r.flushdb()
    osrm = OsrmClient(os.environ.get("OSRM_URL", "http://osrm:5000"))
    bus = LocalBus()
    producer = make_producer()

    m_deps = matching.Deps(index=DriverIndex(r, zone_of), osrm=osrm, bus=bus, producer=producer)
    l_deps = lifecycle.Deps(rides=MemoryRideStore(), connections=MemoryConnectionStore(),
                            bus=bus, connect_token=TOKEN)
    a_deps = archiver.Deps(storage=archiver.LocalStorage(ARCHIVE_DIR))
    gateway = WebSocketGateway(l_deps)
    l_deps.post = gateway.post

    def ride_requested(e): return matching.handle_ride_requested(e, m_deps)
    def lifecycle_update(e): return lifecycle.handle_lifecycle(e, l_deps)
    def notify(e): return lifecycle.handle_notify(e, l_deps)
    def trip_completed(e): return archiver.handle_trip_completed(e, a_deps)

    lifecycle_types = [t for t in events.LIFECYCLE_EVENTS if t != events.RIDE_REQUESTED]
    bus.rule([events.RIDE_REQUESTED], ride_requested)
    bus.rule(lifecycle_types, lifecycle_update)
    bus.rule(list(events.LIFECYCLE_EVENTS) + [events.POSITIONS_SNAPSHOT], notify)
    bus.rule([events.TRIP_COMPLETED], trip_completed)

    threads = [
        ("matching", events.TOPIC_POSITIONS, lambda e: matching.handle_positions(e, m_deps), 1000),
        ("archiver", events.TOPIC_POSITIONS, lambda e: archiver.handle_positions(e, a_deps), 10000),
    ]
    for group, topic, handler, window in threads:
        threading.Thread(target=consume_batches, args=(group, topic, handler, window), daemon=True).start()

    def relay_simulator_events():
        consumer = make_consumer([events.TOPIC_LOCAL_EVENTS], "harness-events")
        for msg in consumer:
            bus.put(msg.value["detail-type"], msg.value["detail"])

    threading.Thread(target=relay_simulator_events, daemon=True).start()
    asyncio.run(gateway.run())


if __name__ == "__main__":
    main()
