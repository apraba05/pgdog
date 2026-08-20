# Mini-PgDog: Go Read/Write Router with Health-Aware Failover

Postgres wire-protocol proxying, connection pooling/multiplexing, replica-aware routing, and failover detection using Redis as the health-state store.

**Live demo:** https://pgdog.ashanpraba.com

The demo runs entirely in the browser against seeded data — no API keys,
no accounts, and no external services required.

## Stack

- Go
- pgx/pgproto3
- Redis
- Docker Compose
- Helm
- Kubernetes (kind/minikube)

## How it works

- Docker-compose up two Postgres containers tagged primary/replica with a seeded table.
- Write a Go TCP proxy using pgproto3 to peek at incoming SQL (regex: SELECT vs INSERT/UPDATE) and route accordingly.
- A bounded connection pool (goroutine worker pool, e.g. 5 backend conns) that multiplexes many concurrent client TCP connections.
- Run a background health-checker that pings the replica every second and writes status to Redis; proxy consults Redis before routing reads.
- Kill the replica container mid-demo and show reads automatically fall back to primary via Redis-flagged state.
- Packaged as a Helm chart, deploy to local kind cluster, and run a quick load script (pgbench or simple Go client loop) to show pooling in logs.

## Running locally

```bash
cd src
bash run.sh
```

Then open the printed URL. A prebuilt static version of the UI lives in
`src/web/` and can be opened directly with no server.
