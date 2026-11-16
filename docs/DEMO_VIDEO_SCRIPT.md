# Demo video script (about 8 minutes)

Record the terminal (Windows: Win+Alt+R with Xbox Game Bar, or OBS). Keep the
topology diagram open in a second window. Before recording: `sudo make down && sudo make up`.

| # | Time | Show | Command | Say |
|---|---|---|---|---|
| 1 | 0:00 | Diagram | `docs/topology.svg` | Option 14. Four zones, five segments, two routers, all in network namespaces on one host. Clients never touch Redis. |
| 2 | 0:45 | One-command launch | `sudo make up` | Namespaces, links, routes, firewall, Redis, API. Dataset import: 10,000 AI4I rows. |
| 3 | 1:30 | Health checks | `sudo make test` | 26 automated checks: routing, allowed paths, denied paths, service round trip. |
| 4 | 2:15 | Routing | `sudo ip netns exec pw-plant traceroute -n -I 10.14.2.10` | Two router hops between plant and API. |
| 5 | 2:45 | Service | `sudo make demo` then `sudo ip netns exec pw-plant curl --cacert run/certs/ca.pem https://api.plantwatch.lab:8443/alerts?count=3` | Replaying dataset rows as live telemetry; alerts are raised by the rules. Create, read, update all go through HTTPS to Redis. |
| 6 | 3:45 | Security: allowed | `sudo ip netns exec pw-plant curl -v --cacert run/certs/ca.pem https://api.plantwatch.lab:8443/health 2>&1 \| grep -E "SSL connection\|verify\|HTTP/"` | TLS 1.3, certificate verified against the lab CA. |
| 7 | 4:15 | Security: denied | `sudo ip netns exec pw-plant nc -vz -w 3 10.14.3.10 6379` and `sudo ip netns exec pw-r2 nft list counters` | The router answers with admin-prohibited; the deny counter increases. |
| 8 | 4:45 | Packets | Open `evidence/D_observability/2_r2_wan_tls.pcap` and `3_r2_data_redis.pcap` in Wireshark | Same transaction at two points: encrypted on the WAN, Redis commands inside the data segment. |
| 9 | 5:30 | Congestion | `sudo experiments/impair.sh delay 50 10`, `sudo ip netns exec pw-plant ping -c 5 10.14.2.10`, `sudo ip netns exec pw-plant .venv/bin/python client/roundtrip.py`, then `sudo experiments/impair.sh clear` | RTT goes from under 1 ms to about 100 ms; request latency follows; server time does not. Show the table in `evidence/results.md`. |
| 10 | 6:30 | Failure and recovery | Terminal 1: `sudo ops/watchdog.sh /tmp/wd.log`. Terminal 2: `sudo lab/services.sh stop api`, watch, then `sudo ip netns exec pw-plant .venv/bin/python client/roundtrip.py` | Three failed probes, diagnosis, restart, healthy again; the same client transaction passes. Mention the Redis and link faults and show the timeline chart. |
| 11 | 7:30 | Wrap up | `evidence/results.md` charts | One sentence each: what the network did to latency, how long recovery took, one limitation. |

Tips: enlarge the terminal font, run each command once beforehand, and pause on
outputs long enough to read them.
