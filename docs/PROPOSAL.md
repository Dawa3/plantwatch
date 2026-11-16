# Proposal checkpoint: PlantWatch (Option 14, Industrial IoT and Predictive Maintenance)

**Team.** Individual project: Dawa Sherpa covers the network, platform and validation roles.

**Purpose.** Collect machine telemetry from a plant floor, store it in Redis in a
separate network, raise predictive-maintenance alerts, and measure how the network
affects alert delivery.

**Inputs / outputs / operations.**
Input: readings (temperatures, speed, torque, tool wear) replayed from the AI4I 2020 dataset.
Output: latest machine state, history, alerts.
Operations: create reading, read state/history, update alert threshold, read/acknowledge alerts.

**Topology.** Segment 1 clients 10.14.1.0/24, segment 2 API 10.14.2.0/24, segment 3
Redis 10.14.3.0/24, segment 4 operations 10.14.4.0/24, transit 10.14.0.0/30. Two
Linux routers with static routes; Linux network namespaces on one workstation.

**Module mapping.** A: namespaces, veth, static routing. B: FastAPI + Redis.
C: nftables allow-list on the data-centre router, TLS on client ↔ API.
D: tcpdump at three points, JSON request log, counters. E: tc netem / tbf on the
transit link. F: Makefile deployment, validation suite, watchdog recovery.

**Test plan.**
Baseline: ping, iperf3, fixed benchmark workload.
Congestion: +50 ms delay, 5 % loss, 2 Mbit/s rate limit; same workload.
Security denial: plant → Redis tcp/6379 must be rejected; client without the CA must fail TLS.
Failure and recovery: kill API, kill Redis, take the WAN link down; watchdog restores; same client transaction before and after.
