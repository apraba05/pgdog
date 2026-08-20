#!/usr/bin/env python3
"""Mini-PgDog browser demo: a dependency-free, stateful routing simulator."""
import json
import os
import random
import threading
import time
from collections import deque
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))


class Demo:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.replica_up = True
        self.redis_healthy = True
        self.pool_size = 5
        self.rate = 8
        self.read_percent = 72
        self.auto = True
        self.next_id = 1042
        self.requests = deque(maxlen=28)
        self.events = deque(maxlen=30)
        self.latencies = deque([12, 9, 14, 11, 8, 15, 10, 13, 9, 12], maxlen=40)
        self.total = 1284
        self.reads = 918
        self.writes = 366
        self.fallbacks = 0
        self.active = 3
        self.queued = 1
        self.add_event("system", "Demo traffic started — 50 clients share 5 backend slots")
        for kind, sql, target in [
            ("read", "SELECT * FROM orders WHERE id = 8421", "replica"),
            ("read", "SELECT count(*) FROM events", "replica"),
            ("write", "UPDATE inventory SET stock = stock - 1", "primary"),
            ("read", "SELECT name, plan FROM customers LIMIT 20", "replica"),
            ("write", "INSERT INTO audit_log VALUES (…) ", "primary"),
        ]:
            self.add_request(kind, sql, target, random.randint(7, 18))

    def add_event(self, kind, message):
        self.events.appendleft({"kind": kind, "message": message, "at": time.strftime("%H:%M:%S")})

    def add_request(self, kind, sql, target, latency):
        self.next_id += 1
        self.requests.appendleft({"id": self.next_id, "kind": kind, "sql": sql,
                                  "target": target, "latency": latency,
                                  "at": time.strftime("%H:%M:%S")})

    def tick(self):
        reads = ["SELECT * FROM orders WHERE status = 'paid'", "SELECT count(*) FROM sessions",
                 "SELECT sku, stock FROM inventory LIMIT 50", "SELECT region, sum(total) FROM orders GROUP BY region"]
        writes = ["INSERT INTO events (type, payload) VALUES (…) ", "UPDATE inventory SET stock = stock - 1",
                  "INSERT INTO audit_log (actor, action) VALUES (…) "]
        with self.lock:
            if not self.auto:
                return
            burst = max(1, round(self.rate / 4))
            capacity = self.pool_size
            self.active = min(capacity, random.randint(max(1, capacity - 2), capacity))
            demand = max(0, round(self.rate * random.uniform(.5, 1.35)) - capacity)
            self.queued = min(50, demand)
            for _ in range(burst):
                read = random.randrange(100) < self.read_percent
                kind = "read" if read else "write"
                target = "replica" if read and self.redis_healthy else "primary"
                base = random.randint(6, 16) + self.queued * 2
                if read and not self.redis_healthy:
                    base += 9
                    self.fallbacks += 1
                self.total += 1
                self.reads += int(read)
                self.writes += int(not read)
                self.latencies.append(base)
                self.add_request(kind, random.choice(reads if read else writes), target, base)

    def action(self, data):
        action = data.get("action")
        with self.lock:
            if action == "replica":
                self.replica_up = not self.replica_up
                if not self.replica_up:
                    self.add_event("danger", "Replica stopped — health check will detect it in 1s")
                else:
                    self.add_event("success", "Replica restarted — waiting for health check")
                threading.Timer(1.0, self.health_sync).start()
            elif action == "burst":
                self.rate = 42
                self.add_event("warning", "Traffic burst: 42 req/s hitting the bounded pool")
                threading.Timer(5.0, self.end_burst).start()
            elif action == "query":
                kind = data.get("kind", "read")
                read = kind == "read"
                target = "replica" if read and self.redis_healthy else "primary"
                latency = random.randint(7, 16) + (9 if read and target == "primary" else 0)
                self.total += 1; self.reads += int(read); self.writes += int(not read)
                self.fallbacks += int(read and target == "primary")
                sql = "SELECT * FROM orders WHERE id = 8421" if read else "INSERT INTO orders (customer_id, total) VALUES (104, 89.00)"
                self.add_request(kind, sql, target, latency)
                self.latencies.append(latency)
                self.add_event("route", f"Manual {kind.upper()} routed to {target}")
            elif action == "settings":
                self.pool_size = max(1, min(12, int(data.get("pool", self.pool_size))))
                self.rate = max(1, min(50, int(data.get("rate", self.rate))))
                self.read_percent = max(0, min(100, int(data.get("reads", self.read_percent))))
            elif action == "auto":
                self.auto = not self.auto
                self.add_event("system", "Traffic resumed" if self.auto else "Traffic paused")

    def health_sync(self):
        with self.lock:
            self.redis_healthy = self.replica_up
            if self.replica_up:
                self.add_event("success", "Health check passed → Redis replica:healthy")
            else:
                self.add_event("danger", "Health check failed → Redis replica:down; reads fail over")

    def end_burst(self):
        with self.lock:
            self.rate = 8
            self.add_event("success", "Burst drained — pool queue returned to normal")

    def state(self):
        with self.lock:
            avg = round(sum(self.latencies) / len(self.latencies))
            return {"replica_up": self.replica_up, "redis_healthy": self.redis_healthy,
                    "pool_size": self.pool_size, "rate": self.rate, "read_percent": self.read_percent,
                    "auto": self.auto, "total": self.total, "reads": self.reads, "writes": self.writes,
                    "fallbacks": self.fallbacks, "active": self.active, "queued": self.queued,
                    "avg_latency": avg, "latencies": list(self.latencies),
                    "requests": list(self.requests), "events": list(self.events)}


demo = Demo()


def ticker():
    while True:
        time.sleep(.6)
        demo.tick()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if urlparse(self.path).path == "/api/state":
            body = json.dumps(demo.state()).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
            return
        if self.path == "/": self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/action": self.send_error(404); return
        try:
            size = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(size) or b"{}")
            demo.action(data)
            body = json.dumps({"ok": True}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(body)
        except Exception as exc:
            self.send_error(400, str(exc))


if __name__ == "__main__":
    threading.Thread(target=ticker, daemon=True).start()
    print(f"Mini-PgDog ready at http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
