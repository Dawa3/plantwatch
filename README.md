# PlantWatch

**Industrial IoT and predictive-maintenance telemetry on a secured, routed network.**
CSCI 414/514 Platform Based Development, Final Practical Exam, application option 14.

Simulated machines on a plant floor send sensor readings over HTTPS to an API in a
data centre. The API stores them in Redis, raises predictive-maintenance alerts,
and an operations zone monitors the service. Everything runs on one Linux host
(tested on Ubuntu 24.04, also intended for WSL2 Ubuntu) using network namespaces.

## Topology

```
 PLANT ZONE (clients)                                        SERVICE ZONE
 10.14.1.0/24                                                10.14.2.0/24
 +-------------+                                             +----------------------+
 | pw-plant    |                                             | pw-api  10.14.2.10   |
 | .10         |--+                                       +--| FastAPI, HTTPS :8443 |
 | simulators, |  |   +---------+  WAN/transit  +-------+ |  | iperf3 :5201         |
 | benchmark   |  +---| pw-r1   | 10.14.0.0/30  | pw-r2 |-+  +----------------------+
 +-------------+      | edge    |---------------| DC    |
                      | router  | .1         .2 | router|    DATA ZONE
 OPERATIONS ZONE  +---| nft     |  tc netem/tbf | nft   |-+  10.14.3.0/24
 10.14.4.0/24     |   +---------+  applied here | fwd:  | |  +----------------------+
 +-------------+  |                             | drop  | +--| pw-db   10.14.3.10   |
 | pw-ops .10  |--+                             +-------+    | Redis :6379 (AOF)    |
 | monitor,    |                                             | host firewall        |
 | watchdog,   |                                             +----------------------+
 | alert watch |
 +-------------+
```

A drawn version is in [`docs/topology.svg`](docs/topology.svg).

| Zone | Namespace | Segment | Host | Gateway |
|---|---|---|---|---|
| Client (plant floor) | `pw-plant` | 10.14.1.0/24 | 10.14.1.10 | pw-r1 10.14.1.1 |
| Service (API) | `pw-api` | 10.14.2.0/24 | 10.14.2.10 | pw-r2 10.14.2.1 |
| Data (Redis) | `pw-db` | 10.14.3.0/24 | 10.14.3.10 | pw-r2 10.14.3.1 |
| Operations | `pw-ops` | 10.14.4.0/24 | 10.14.4.10 | pw-r1 10.14.4.1 |
| Transit | `pw-r1`, `pw-r2` | 10.14.0.0/30 | .1 and .2 | static routes both ways |

Traffic policy (enforced on `pw-r2`, forward policy `drop`):

| From | To | Allowed |
|---|---|---|
| plant, ops | API | tcp/8443 (HTTPS), ICMP echo |
| plant | API | tcp/5201 (iperf3 measurement) |
| API | Redis | tcp/6379 with password |
| ops | Redis host | ICMP echo only |
| plant, ops | Redis | **denied** (ICMP admin-prohibited) |
| plant | ops | **denied** on `pw-r1` |
| anything else | | **denied** |

## Quick start

```bash
sudo make setup        # once: packages, Python venv, .env secret, TLS certs, dataset, kernel check
sudo make up           # build the network, start Redis + API, import the dataset
sudo make test         # 26 automated health / policy checks
sudo make experiments  # modules A-F, about 5 minutes, writes evidence/
sudo make down
```

Single modules: `sudo make A` ... `sudo make F`. Rebuild tables and charts from
existing raw data: `make report`. Live demo traffic: `sudo make demo`.

### WSL2 notes

* Work inside the Linux filesystem (for example `~/plantwatch`), not under `/mnt/c`.
* `sudo make preflight` checks the kernel. If it reports that **netem** is missing,
  run `wsl --update` and `wsl --shutdown` in PowerShell, then try again. Without
  netem the loss test falls back to an nftables random-drop rule and the rate
  test uses `tbf`, but the delay profile is skipped.
* Open the captures in Wireshark on Windows from
  `\\wsl$\Ubuntu\home\<you>\plantwatch\evidence\`.

## The six modules and where their evidence lands

| Module | What is implemented | Script | Evidence |
|---|---|---|---|
| A Network infrastructure | 5 IP segments, 2 routers, static routing | `lab/up.sh`, `experiments/A_network.sh` | `evidence/A_network/connectivity.txt` |
| B Distributed service | FastAPI + Redis, create / read / update, error responses | `app/`, `experiments/B_service.sh` | `evidence/B_service/queries.txt` |
| C Network security | nftables on both routers and the Redis host, TLS 1.3 with a private CA | `lab/firewall-*.nft`, `lab/gen_certs.sh`, `experiments/C_security.sh` | `evidence/C_security/` (text + pcap) |
| D Observability | 3-point packet capture of one transaction, JSON request log, counters | `experiments/D_observability.sh` | `evidence/D_observability/` (text + 3 pcap) |
| E Network performance | baseline vs delay / loss / rate limit vs recovered, identical workload | `experiments/E_performance.sh`, `impair.sh`, `client/bench.py` | `evidence/E_performance/`, `evidence/results.md` |
| F Automation and recovery | one-command deploy, validation suite, watchdog that detects, diagnoses and repairs 3 faults | `Makefile`, `experiments/validate.sh`, `ops/watchdog.sh`, `experiments/F_recovery.sh` | `evidence/F_recovery/`, `evidence/results.md` |

## API

Base URL `https://api.plantwatch.lab:8443` (resolves inside the namespaces). From the host:

```bash
sudo ip netns exec pw-plant curl --cacert run/certs/ca.pem https://api.plantwatch.lab:8443/health
```

| Method and path | Purpose |
|---|---|
| `POST /telemetry` | store a reading, update machine state, raise alerts (201) |
| `GET /machines` | list machine ids |
| `GET /machines/{id}` | latest state of a machine (404 if unknown) |
| `GET /machines/{id}/readings?count=N` | recent readings, newest first |
| `PUT /machines/{id}/config` | change the tool-wear alert threshold |
| `GET /alerts?count=N` / `GET /alerts?after=<id>` | newest alerts / alerts since an id |
| `POST /alerts/{id}/ack` | acknowledge an alert |
| `GET /stats`, `GET /health` | counters / liveness including Redis reachability (503 if Redis is down) |

Every response carries `X-Request-Id`, `X-App-Ms` (time inside the API) and
`X-Db-Ms` (time waiting for Redis). The client subtracts `X-App-Ms` from its own
total to obtain network time.

## Redis data model

| Key | Type | Content | Used by |
|---|---|---|---|
| `machines` | SET | all machine ids | list, existence checks |
| `machine:{id}` | HASH | latest values, status, `tool_wear_limit`, `readings` counter | O(1) latest-state read, config update |
| `telemetry:{id}` | STREAM | time-ordered readings (capped at about 2000) | history query with `XREVRANGE ... COUNT n` |
| `alerts` | STREAM | alert events of all machines | newest-first and "since id" polling |
| `alerts:acked` | HASH | alert id to acknowledgement time | ack |
| `stats` | HASH | global counters, import metadata | `/stats` |

A write is one `MULTI`/`EXEC` pipeline (one network round trip to Redis after
a single `HGET` for the threshold). Durability: append-only file, `fsync` every second.

## Dataset

**AI4I 2020 Predictive Maintenance Dataset**, S. Matzka (2020), UCI Machine
Learning Repository, <https://doi.org/10.24432/C5HS5C>, licensed CC BY 4.0.
10,000 rows: air and process temperature, rotational speed, torque, tool wear,
failure labels. The dataset itself is synthetic (stated by its author).

* `data/get_dataset.sh` downloads `ai4i2020.csv` (not committed to this repository).
* `data/import_dataset.py` loads all 10,000 rows into Redis. The dataset has no
  machine or time column, so rows are dealt to 20 simulated machines with
  timestamps one minute apart: **machine id and timestamp are synthetic, sensor
  values and failure labels come from the dataset** (`source=ai4i2020`).
* Live traffic is labelled by origin: `replay` (dataset rows re-sent by
  `client/replay.py`), `bench`, `roundtrip`, `trace`, `demo`.
* If the download is not possible, `data/make_synthetic.py` generates stand-in
  rows labelled `source=synthetic-generator`. Check `GET /stats` → `import_source`
  to see which one a deployment uses.

Alert rules (`app/rules.py`) are the failure-mode definitions published with the dataset.

## Repository layout

```
lab/          network build, firewall rulesets, certificates, service control
app/          FastAPI service and alert rules
data/         dataset download, ETL, fallback generator
client/       benchmark, replay simulator, round-trip check, traced request
ops/          health monitor, alert consumer, watchdog (automated recovery)
experiments/  one script per module A-F, impairment tool, report generator
docs/         report, proposal, demo script, slide outline, topology diagram
evidence/     generated outputs: text, pcap, csv, charts, results.md
```

## Secrets

`.env` (Redis password) and `run/certs/*.key` are generated locally by
`make setup` and are git-ignored. `experiments/D_observability.sh` refuses to
keep a capture that contains the Redis `AUTH` exchange.

## Known limitations

* API to Redis traffic is plaintext inside the data segment (shown on purpose in
  Module D). It is protected by segmentation, two firewalls and a password, not
  by encryption. Redis TLS would be the next step.
* One host, one kernel: latency in the baseline is far lower than on real links,
  and CPU contention between namespaces can add noise.
* Routing is static. FRRouting / OSPF between the two routers is a possible extension.
* The watchdog runs on the host with root rights; in production it would be an
  orchestrator or init system.
