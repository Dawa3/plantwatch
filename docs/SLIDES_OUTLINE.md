# Slide outline (10 slides)

1. **Title.** PlantWatch: industrial IoT telemetry on a secured, routed network. Option 14. Name, course, date.
2. **Problem and scope.** Machines → API → Redis → alerts. Small app on purpose; network engineering is the subject.
3. **Architecture.** `docs/topology.svg`. Five segments, two routers, where each service lives.
4. **End-to-end transaction.** Client → pw-r1 → pw-r2 → API → Redis and back; the three capture points.
5. **Service and data.** Endpoints, Redis key design (hash for latest state, stream for history and alerts), AI4I 2020 dataset and what is synthetic.
6. **Security.** Policy table; TLS 1.3 with private CA; allowed vs denied evidence (curl verify OK, ICMP admin-prohibited, counters).
7. **Observability.** Request id across client, API log and two captures; encrypted on WAN, plaintext RESP in the data segment.
8. **Performance.** `chart_latency_by_condition.png` and `chart_time_breakdown.png`. One line per impairment: what changed and why (round trips, retransmission timeouts, size ÷ rate).
9. **Failure and recovery.** `chart_recovery_timeline.png` and the outage table. Detection, diagnosis, action, proof. The lost-static-routes detail.
10. **Lessons and limitations.** Plaintext Redis segment, single host, static routing, small samples; next steps.
