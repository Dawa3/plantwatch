#!/usr/bin/env python3
"""Build the full written report from the evidence folder.

    python experiments/build_report.py --author "Your Name"

Writes docs/FINAL_REPORT.md. Every table, number and terminal excerpt is read
from evidence/ at build time, and the four figures are linked from docs/ and
evidence/. Convert to Word or PDF with pandoc (see the end of the output).
"""
import argparse
import os
import platform
import re
import subprocess
import time

import make_report as mr

ROOT = mr.ROOT
EVID = mr.EVID
DOCS = os.path.join(ROOT, "docs")
SEC = re.compile(r"^=+ (.*?) =+$")


def read(rel):
    p = os.path.join(EVID, rel)
    return open(p, errors="replace").read() if os.path.exists(p) else ""


def section(text, starts, max_lines=40, strip_cmd_exit=True):
    """Body of the first '==== title ====' section whose title starts with `starts`."""
    out, on = [], False
    for line in text.splitlines():
        m = SEC.match(line.strip())
        if m:
            if on:
                break
            on = m.group(1).startswith(starts)
            continue
        if on:
            if strip_cmd_exit and line.startswith("[exit "):
                continue
            out.append(line.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    if len(out) > max_lines:
        out = out[:max_lines] + ["..."]
    return "\n".join(l[:150] for l in out)


def grep(text, pattern, limit=20):
    return "\n".join([l.rstrip()[:150] for l in text.splitlines() if re.search(pattern, l)][:limit])


def code(body, missing="(no evidence file found - run the module's script)"):
    return "```text\n" + (body if body.strip() else missing) + "\n```"


def fig(path_from_docs, caption, n):
    return f"![Figure {n}. {caption}]({path_from_docs})\n\n*Figure {n}. {caption}*"


def counters(text):
    """{name: packets} from an `nft list counters` block."""
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"counter (\w+) \{\s*packets (\d+)", text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", default="[your name]")
    ap.add_argument("--out", default=os.path.join(DOCS, "FINAL_REPORT.md"))
    a = ap.parse_args()

    A = read("A_network/connectivity.txt")
    B = read("B_service/queries.txt")
    C = read("C_security/security.txt")
    D = read("D_observability/observability.txt")
    F = read("F_recovery/recovery.txt")
    V = read("validate.txt")

    conds = [c for c in (mr.load_condition(l) for l in mr.LABELS) if c]
    by = {c["label"]: c for c in conds}
    ra = mr.recovery_analysis()
    f = mr.f

    def op(label, name, key):
        return by[label]["ops"][name][key] if label in by else float("nan")

    kernel = platform.release()
    try:
        distro = subprocess.run(["lsb_release", "-ds"], capture_output=True, text=True).stdout.strip() or platform.platform()
    except OSError:
        distro = platform.platform()

    stats = re.search(r'"imported_rows":"(\d+)","import_source":"([\w-]+)","imported_alerts":"(\d+)"', B + F)
    imp_rows, imp_src, imp_alerts = stats.groups() if stats else ("?", "?", "?")
    tls_ver = (re.search(r"Protocol version: (\S+)", C) or [None, "?"])[1]
    tls_cipher = (re.search(r"Ciphersuite: (\S+)", C) or [None, "?"])[1]
    c_before = counters(section(C, "Counters before", 60))
    c_after = counters(section(C, "Counters after the tests (pw-r2)", 60))
    trace_tls = (re.search(r"client-side capture \(TLS\)\s*: (\d+)", D) or [None, "?"])[1]
    trace_resp = (re.search(r"data-segment capture \(RESP\): (\d+)", D) or [None, "?"])[1]
    v_res = (re.search(r"Result: (\d+) passed, (\d+) failed", V) or [None, "?", "?"])
    totals = re.findall(r'"readings_total":"(\d+)"', F)

    L = []
    w = L.append
    n = [0]

    def figure(path, caption):
        n[0] += 1
        w(fig(path, caption, n[0]))
        w("")

    w("# PlantWatch: a secured, routed platform for industrial IoT telemetry")
    w("")
    w("CSCI 414/514 Platform Based Development · Final Practical Exam · Option 14 (Industrial IoT and Predictive Maintenance)")
    w("")
    w(f"Author: {a.author} (individual submission) · {time.strftime('%B %Y')}")
    w("")
    w(f"Environment: {distro}, kernel {kernel}. All numbers, tables and terminal excerpts in this report were "
      "read from the `evidence/` folder of the repository by `experiments/build_report.py`.")
    w("")

    # ------------------------------------------------------------------ 1
    w("## 1. Purpose and scope")
    w("")
    w("PlantWatch collects sensor readings from machines on a plant floor, stores them in a NoSQL datastore in a "
      "separate data-centre network, and raises predictive-maintenance alerts that an operations team consumes. "
      "The application is deliberately small. The object of study is the network platform under it: segmentation, "
      "routing, access control, encryption, observability, behaviour under congestion, and recovery from failure.")
    w("")
    w("| | |")
    w("|---|---|")
    w("| Inputs | Readings per machine: air temperature, process temperature, rotational speed, torque, tool wear |")
    w("| Outputs | Latest machine state, reading history, alerts |")
    w("| Operations | Create a reading, read state and history, update an alert threshold, read and acknowledge alerts |")
    w("| Stack | Linux network namespaces, nftables, FastAPI over TLS, Redis, tc netem / tbf, tcpdump, iperf3 |")
    w("")

    # ------------------------------------------------------------------ 2
    w("## 2. Architecture")
    w("")
    figure("topology.png", "Topology: four zones, five IP segments and two routers on one Linux host")
    w("| Segment | Prefix | Members |")
    w("|---|---|---|")
    w("| 1 Client (plant floor) | 10.14.1.0/24 | pw-plant .10, pw-r1 .1 |")
    w("| 2 Application | 10.14.2.0/24 | pw-api .10, pw-r2 .1 |")
    w("| 3 Data | 10.14.3.0/24 | pw-db .10, pw-r2 .1 |")
    w("| 4 Operations | 10.14.4.0/24 | pw-ops .10, pw-r1 .1 |")
    w("| Transit (WAN) | 10.14.0.0/30 | pw-r1 .1, pw-r2 .2 |")
    w("")
    w("**End-to-end transaction.** A client in segment 1 opens TCP and then TLS to 10.14.2.10:8443. pw-r1 forwards "
      "the packets over the transit link using a static route. pw-r2's firewall accepts tcp/8443 and forwards to the "
      "application segment. The API sends `HGET` and then one `MULTI ... EXEC` pipeline to Redis at 10.14.3.10:6379, "
      "again through pw-r2. The response returns along the same path with a request id and timing headers.")
    w("")
    w("**Data placement.** Redis is one router hop from the API and three hops from the clients. A write costs the "
      "client one round trip over the WAN plus two Redis round trips inside the data centre, so the WAN dominates "
      "client latency as soon as it is impaired while datastore time stays constant (Section 6). Keeping the database "
      "off the client path is also what makes the rule \"clients cannot bypass the API\" enforceable.")
    w("")

    # ------------------------------------------------------------------ 3
    w("## 3. Implementation and evidence by module")
    w("")
    w("### 3.1 Module A: network infrastructure")
    w("")
    w("`lab/up.sh` creates six namespaces and five veth links, assigns addresses, enables IPv4 forwarding on the two "
      "routers only, and installs static routes: a default route on each host and two /24 routes per router across "
      "the transit link.")
    w("")
    w("Route tables of the two routers:")
    w("")
    rt = section(A, "Route tables", 60)
    rt_r = "\n".join(l for blk in re.split(r"(?=^--- )", rt, flags=re.M) if blk.startswith(("--- pw-r1", "--- pw-r2"))
                     for l in blk.strip().splitlines())
    w(code(rt_r))
    w("")
    w("Path from the plant zone to the API (two router hops) and baseline round-trip time:")
    w("")
    w(code(section(A, "Path: plant -> API", 12) + "\n\n" + grep(section(A, "Reachability", 20), r"packets transmitted|rtt")))
    w("")
    w("Connectivity matrix. \"works\" rows are intended paths; \"blocked\" rows are intended boundaries:")
    w("")
    w(code(grep(A, r"^\s+(PASS|FAIL)|^Result:")))
    w("")
    w("### 3.2 Module B: distributed service")
    w("")
    w("The API is FastAPI served by uvicorn over TLS (`app/main.py`); Redis is the datastore. The key design follows "
      "the queries the API runs:")
    w("")
    w("| Key | Type | Content | Query it serves |")
    w("|---|---|---|---|")
    w("| `machines` | SET | all machine ids | listing, existence checks |")
    w("| `machine:{id}` | HASH | latest values, status, `tool_wear_limit`, counter | latest state in one `HGETALL`; threshold update |")
    w("| `telemetry:{id}` | STREAM | time-ordered readings, capped | history with `XREVRANGE ... COUNT n` |")
    w("| `alerts` | STREAM | alert events of all machines | newest first; everything since an id |")
    w("| `alerts:acked` | HASH | alert id to acknowledgement time | acknowledge |")
    w("| `stats` | HASH | counters and import metadata | `/stats` |")
    w("")
    w("| Method and path | Operation |")
    w("|---|---|")
    w("| `POST /telemetry` | CREATE a reading, UPDATE machine state, raise alerts |")
    w("| `GET /machines/{id}`, `GET /machines/{id}/readings` | READ latest state / history |")
    w("| `PUT /machines/{id}/config` | UPDATE the tool-wear alert threshold |")
    w("| `GET /alerts`, `POST /alerts/{id}/ack` | READ alerts / UPDATE acknowledgement |")
    w("| `GET /health`, `GET /stats` | liveness including Redis reachability / counters |")
    w("")
    w("Create with an alert (a worn tool exceeds the 200-minute threshold), then read the state back:")
    w("")
    w(code(section(B, "CREATE - POST /telemetry (worn tool", 8) + "\n\n" + section(B, "READ - GET /machines/DEMO01 (latest", 8)))
    w("")
    w("Update, and its effect (the same reading no longer raises an alert once the threshold is 240):")
    w("")
    w(code(section(B, "UPDATE - PUT", 8) + "\n\n" + section(B, "Effect of the update", 8)))
    w("")
    w("Error responses:")
    w("")
    w(code(section(B, "ERROR - unknown machine", 6) + "\n\n" + section(B, "ERROR - out-of-range", 6)
           + "\n\n" + section(B, "ERROR - wrong method", 6)))
    w("")
    w("Stored structures as seen with `redis-cli` from the service zone:")
    w("")
    rs = section(B, "Redis data model", 200)
    keep, on = [], False
    for line in rs.splitlines():
        if line.startswith("$ redis-cli"):
            on = any(k in line for k in ("INFO keyspace", "SCARD machines", "TYPE machine:M01", "TYPE telemetry:M01",
                                         "XLEN telemetry:M01", "XLEN alerts", "HGETALL stats", "CONFIG GET appendonly"))
        if on and line.strip():
            keep.append(line)
    w(code("\n".join(keep[:45])))
    w("")
    w(f"The datastore holds {imp_rows} imported readings (requirement: at least 1,000) plus the live readings written "
      "during the experiments.")
    w("")
    w("### 3.3 Module C: network security")
    w("")
    w("**Access control.** pw-r2 forwards with policy `drop` and an explicit allow-list. pw-r1 adds anti-spoofing and "
      "blocks plant to operations. The Redis host has its own input filter that accepts tcp/6379 from the API address "
      "only, and Redis requires a password.")
    w("")
    w("| From | To | Decision |")
    w("|---|---|---|")
    w("| plant, ops | API tcp/8443 (HTTPS), ICMP echo | allow |")
    w("| plant | API tcp/5201 (iperf3 measurement) | allow |")
    w("| API | Redis tcp/6379 | allow |")
    w("| ops | Redis host, ICMP echo only | allow |")
    w("| plant, ops | Redis | reject (ICMP admin-prohibited) |")
    w("| plant | operations zone | reject on pw-r1 |")
    w("| anything else | | reject |")
    w("")
    w("Forwarding rules loaded on pw-r2:")
    w("")
    rules = section(C, "Ruleset: data-centre router", 80)
    m = re.search(r"chain forward \{.*?\n\t\}", rules, flags=re.S)
    w(code((m.group(0) if m else rules).replace("\t", "  ")))
    w("")
    w(f"**Encryption.** Client to API traffic uses {tls_ver} with cipher suite {tls_cipher}. The server certificate is "
      "issued by a private lab CA and clients verify it against that CA only:")
    w("")
    w(code(grep(section(C, "TLS: what the client negotiates", 40), r"Protocol version|Ciphersuite|Peer certificate|Verification|subject=|issuer=|DNS:")))
    w("")
    w("**Permitted and denied traffic.** Twelve policy checks, each executed as a real connection attempt:")
    w("")
    w(code(grep(section(C, "Pass/fail summary", 30), r"PASS|FAIL") + "\n" + grep(C, r"^Result:")))
    w("")
    w("Packet-level proof of the denial. The client's SYN to Redis reaches pw-r2 and is answered with ICMP "
      "\"admin prohibited\"; no packet reaches the data segment:")
    w("")
    w(code(grep(C, r"10\.14\.3\.10\.6379: Flags \[S\]|admin prohibited", 4)))
    w("")
    if c_before and c_after:
        w("Firewall counters on pw-r2 before and after the test run (packets):")
        w("")
        w("| Counter | Before | After |")
        w("|---|---:|---:|")
        for k in ("allow_https", "allow_api_db", "allow_icmp", "deny_to_data", "deny_other"):
            if k in c_after:
                w(f"| `{k}` | {c_before.get(k, 0)} | {c_after[k]} |")
        w("")
    w("TLS and the firewall do different jobs. TLS protects the content of the permitted path; a client that does "
      "not trust the lab CA is rejected during the handshake. The firewall decides which paths exist; a client aiming "
      "at Redis is rejected by the router before any application protocol is spoken.")
    w("")
    w("### 3.4 Module D: observability")
    w("")
    w("One transaction was traced at three capture points (client interface, pw-r2 WAN side, pw-r2 data side) and "
      "matched against the logs by its request id.")
    w("")
    w("Client view and the API log lines for the same request ids:")
    w("")
    cv = section(D, "1. Client view", 30)
    cv = cv.split('  "stored_state"')[0].rstrip().rstrip(",") + "\n}" if '"stored_state"' in cv else cv
    w(code(cv + "\n\n" + section(D, "2. API log lines", 6)))
    w("")
    w("WAN-side capture (tcp/8443): TCP handshake followed by encrypted TLS records:")
    w("")
    w(code(section(D, "3. Capture on pw-r2 r2-wan", 9)))
    w("")
    w("Data-side capture (tcp/6379): the Redis commands of the same transaction are readable:")
    w("")
    w(code(grep(section(D, "4. Capture on pw-r2 r2-data", 40), r"RESP|^HGET|^MULTI", 6)))
    w("")
    w(f"The traced machine id appears {trace_tls} times in the TLS capture and {trace_resp} times in the Redis capture. "
      "Encryption therefore ends at the API; inside the data centre the segment is protected by segmentation and "
      "access control, which Section 7 lists as a limitation.")
    w("")
    w("| Signal | Source | Used for |")
    w("|---|---|---|")
    w("| Packets | tcpdump at three points, `.pcap` files in `evidence/D_observability/` | handshakes, encrypted versus plaintext payload, denied flows |")
    w("| Logs | API JSON request log, Redis log, watchdog log, timestamped event log | correlation by request id and time |")
    w("| Metrics | ping, iperf3, per-request total / API / Redis time, firewall counters, health-probe record | Sections 6.1 and 6.2 |")
    w("")
    w("### 3.5 Module E: network performance")
    w("")
    w("`experiments/impair.sh` applies netem (delay, loss) or tbf (rate limit) to the egress of both routers on the "
      "transit link, so both directions are affected. `experiments/measure.sh` then runs an identical workload. "
      "Results are in Section 6.1.")
    w("")
    w("### 3.6 Module F: automation and recovery")
    w("")
    w("* Deployment: `sudo make setup` once, then `sudo make up` builds the network and starts every service.")
    w(f"* Validation: `sudo make test` runs an automated suite; the last run reported {v_res[1]} passed and {v_res[2]} failed.")
    w("* Recovery: `ops/watchdog.sh` probes `/health` from the operations zone every second. After three consecutive "
      "failures it diagnoses the cause (WAN link and routes, Redis process, API process) and runs the matching repair. "
      "Results are in Section 6.2.")
    w("")

    # ------------------------------------------------------------------ 4, 5
    w("## 4. Experimental method")
    w("")
    w("| State | What changes | Script |")
    w("|---|---|---|")
    w("| 1 Baseline | nothing | `experiments/E_performance.sh` |")
    w("| 2 Congested | delay, loss and rate limit on the WAN link, one at a time, then removed | `experiments/E_performance.sh` |")
    w("| 3 Failure and recovery | API crash, Redis crash, WAN link down | `experiments/F_recovery.sh` |")
    w("")
    w("Workload per condition: 50 pings; a 5 s iperf3 TCP test; and `client/bench.py` with a fixed seed: 100 writes, "
      "100 state reads and 50 history reads (200 readings, about 36 kB) on one keep-alive TLS connection, then 30 reads "
      "each on a new TCP+TLS connection. Every response carries the server's processing time and Redis time, so "
      "network time = client total − server time. Alert delivery is measured by a consumer in the operations zone "
      "that polls every 200 ms. All zones share one clock, so timestamps are directly comparable.")
    w("")
    w("## 5. Dataset")
    w("")
    w("AI4I 2020 Predictive Maintenance Dataset (S. Matzka, 2020, UCI Machine Learning Repository, CC BY 4.0, "
      "https://doi.org/10.24432/C5HS5C): 10,000 rows with air and process temperature, rotational speed, torque, "
      "tool wear and failure labels. The dataset is itself synthetic, as stated by its author.")
    w("")
    w(f"* Imported for this report: {imp_rows} readings and {imp_alerts} labelled-failure alerts, `import_source={imp_src}`.")
    w("* The dataset has no machine or time column. Rows are dealt to 20 simulated machines with timestamps one minute "
      "apart, so machine ids and timestamps are synthetic; sensor values and failure labels are from the dataset.")
    w("* Live records are labelled by origin (`replay`, `bench`, `roundtrip`, `trace`, `demo`).")
    w("* The alert rules are the failure-mode definitions published with the dataset (tool wear, heat dissipation, "
      "power, overstrain).")
    w("")

    # ------------------------------------------------------------------ 6
    w("## 6. Results")
    w("")
    w("### 6.1 Baseline versus degraded network")
    w("")
    if conds:
        w(mr.performance_md(conds))
        w("")
        figure("../evidence/chart_latency_by_condition.png",
               "Request latency by network condition: median (bar) and 95th percentile (tick)")
        figure("../evidence/chart_time_breakdown.png",
               "Where the median telemetry write spends its time: network, API processing, Redis")
        b = by.get("baseline")
        if b and "delay" in by:
            d = by["delay"]
            rtt = d["rtt_avg"] - b["rtt_avg"]
            dw = op("delay", "write", "p50") - op("baseline", "write", "p50")
            dn = op("delay", "newconn_read", "p50") - op("baseline", "newconn_read", "p50")
            dapp = op("delay", "write", "app") - op("baseline", "write", "app")
            w(f"**Delay.** The impairment raised the round-trip time from {f(b['rtt_avg'], 2)} ms to {f(d['rtt_avg'], 2)} ms. "
              f"A request on an existing connection needs one round trip and its median rose by {f(dw)} ms "
              f"({f(dw / rtt, 1)} RTT): writes {f(op('baseline', 'write', 'p50'))} → {f(op('delay', 'write', 'p50'))} ms. "
              f"A request on a new connection needs three round trips (TCP handshake, TLS 1.3 handshake, request) and rose "
              f"by {f(dn)} ms ({f(dn / rtt, 1)} RTT): {f(op('baseline', 'newconn_read', 'p50'))} → "
              f"{f(op('delay', 'newconn_read', 'p50'))} ms. Reusing connections is therefore worth about {f(dn - dw, 0)} ms "
              f"per request on this link. Server-side time for a write changed by only {f(dapp, 2)} ms, "
              f"{f(100 * dapp / dw, 0)} % of the added latency; the rest is the network. TCP throughput fell from "
              f"{f(b['mbps'], 0)} to {f(d['mbps'], 0)} Mbit/s without any rate limit, because a long RTT slows TCP's "
              "window growth and acknowledgement clock.")
            w("")
        if b and "loss" in by:
            l = by["loss"]
            w(f"**Loss.** Ping measured {f(l['ping_loss'], 0)} % round-trip loss over 50 samples. The medians did not move "
              f"(state read {f(op('baseline', 'read_latest', 'p50'))} → {f(op('loss', 'read_latest', 'p50'))} ms) because "
              f"most requests lose no packet. The tail did: the 95th percentile of state reads went from "
              f"{f(op('baseline', 'read_latest', 'p95'))} ms to {f(op('loss', 'read_latest', 'p95'))} ms, and new "
              f"connections reached {f(op('loss', 'newconn_read', 'p95'))} ms at p95 and "
              f"{f(op('loss', 'newconn_read', 'p99'))} ms at p99. These steps match TCP's timers: about 200 ms for the "
              f"minimum retransmission timeout and about 1 s for a lost SYN. {l['requests'] - l['errors']} of "
              f"{l['requests']} requests still succeeded, so TCP converted packet loss into latency, not errors. "
              f"Bulk throughput fell to {f(l['mbps'], 1)} Mbit/s.")
            w("")
        if b and "rate" in by:
            r = by["rate"]
            dh = op("rate", "read_history", "p50") - op("baseline", "read_history", "p50")
            w(f"**Rate limit.** Small requests were almost unaffected (write {f(op('baseline', 'write', 'p50'))} → "
              f"{f(op('rate', 'write', 'p50'))} ms). The 200-reading history response is about 36 kB, and "
              f"36.4 kB × 8 ÷ 2 Mbit/s ≈ 146 ms; the measured increase was {f(dh, 0)} ms "
              f"({f(op('baseline', 'read_history', 'p50'))} → {f(op('rate', 'read_history', 'p50'))} ms). "
              f"iperf3 confirmed {f(r['mbps'], 1)} Mbit/s. Payload size decides which requests suffer.")
            w("")
        if b and b.get("alert_p50") is not None:
            parts = [f"{c['label']} {f(c['alert_p50'])} ms" for c in conds if c.get("alert_p50") is not None]
            w("**Alert delivery.** Median delay from the sensor timestamp to first sight in the operations zone: "
              + ", ".join(parts) + ". Delivery includes up to one 200 ms polling interval, which explains the spread "
              "between the unimpaired runs with only 20 alerts each."
              + (f" Under delay the uplink alone rose from {f(b['uplink_p50'])} ms to {f(by['delay']['uplink_p50'])} ms, "
                 "one direction of the WAN." if "delay" in by else ""))
            w("")
        if b and "recovered" in by:
            r = by["recovered"]
            w(f"**Recovered.** After the impairment was removed the metrics returned to baseline: RTT {f(r['rtt_avg'], 2)} ms, "
              f"write median {f(op('recovered', 'write', 'p50'))} ms, {f(r['mbps'], 0)} Mbit/s.")
            w("")
        if b:
            h = b["ops"]["read_history"]
            w("**Network versus application bottleneck.** In every degraded condition the client-side total grew while "
              "server-reported time stayed close to baseline, so the WAN link is the bottleneck. The one case where the "
              f"application dominates is the history query at baseline: {f(h['db'], 2)} ms of its {f(h['p50'])} ms median "
              f"is Redis (`XREVRANGE` of 200 entries) and only {f(h['net'])} ms is network.")
            w("")
        missing = [x for x in ("delay", "loss", "rate") if x not in by]
        if missing:
            w(f"Not measured on this machine: {', '.join(missing)}.")
            w("")
        w("Caveats: 30 to 100 samples per operation, so p99 rests on one or two requests. iperf3 reports many "
          "retransmits even at baseline because the virtual link runs at several Gbit/s with segmentation offload "
          "disabled; retransmit counts are not comparable across conditions with very different throughput.")
        w("")
    else:
        w("No performance data found. Run `sudo make E`.")
        w("")

    w("### 6.2 Failure and recovery")
    w("")
    if ra:
        w(mr.recovery_md(ra))
        w("")
        figure("../evidence/chart_recovery_timeline.png",
               "Health-probe latency and failed probes during the three injected faults")
        w("* The three faults look different to a client, which is what makes diagnosis possible: a dead API refuses "
          "the connection, a dead Redis leaves the API reachable and it answers HTTP 503, and a dead link produces "
          "unreachable errors and timeouts.")
        det = {r["name"]: r["detect_s"] for r in ra["faults"]}
        if det.get("wan_down") and det.get("api_crash"):
            w(f"* The link fault took longest to detect ({f(det['wan_down'])} s versus {f(det['api_crash'])} s for the API "
              "crash) because each failed probe had to wait for its timeout before it counted towards the three-failure threshold.")
        w("* Bringing the WAN interface back up is not sufficient. Linux removes static routes that use an interface "
          "when it goes down, so the recovery action also re-adds the routes on both routers.")
        if len(totals) >= 4:
            w(f"* Data survived the Redis crash: the reading counter was {int(totals[2]):,} before the crash and "
              f"{int(totals[3]):,} after recovery. The single increment is the post-recovery check itself, so no stored "
              "reading was lost; Redis reloaded its append-only file.")
        w("")
        w("Watchdog log for the three faults (detection, diagnosis, action, recovery):")
        w("")
        w(code(grep(section(F, "Watchdog log", 80), r"DETECTED|DIAGNOSIS|ACTION|RECOVERED", 16)))
        w("")
        w("The same client transaction before, during and after the Redis fault:")
        w("")
        w(code(grep(section(F, "FAULT: Redis", 40), r"^(PASS|FAIL)|HTTP 5|Health check", 6)))
        w("")
    else:
        w("No recovery data found. Run `sudo make F`.")
        w("")

    # ------------------------------------------------------------------ 7-9
    w("## 7. Limitations and next steps")
    w("")
    w("* Redis traffic is unencrypted inside the data segment (shown in Section 3.4). Redis TLS is the next step.")
    w("* Everything runs on one host, so baseline latency is microseconds; real links would shift every number.")
    w("* Routing is static and the WAN link is a single point of failure. A second path with OSPF (FRRouting) would remove it.")
    w("* Sample sizes are small and no confidence intervals are reported.")
    w("* The watchdog runs with root rights on the host; in production an orchestrator would take that role.")
    w("")
    w("## 8. Reproduction")
    w("")
    w("```bash\ngit clone https://github.com/Dawa3/plantwatch && cd plantwatch\n"
      "sudo make setup && sudo make up && sudo make test && sudo make experiments\n"
      "python3 experiments/build_report.py --author \"Your Name\"\n```")
    w("")
    w("| Deliverable | Location |")
    w("|---|---|")
    w("| Source and automation | `lab/`, `app/`, `client/`, `ops/`, `experiments/`, `Makefile` |")
    w("| Evidence | `evidence/` (text outputs, `.pcap` captures, CSV measurements, charts) |")
    w("| Topology diagram | `docs/topology.svg`, `docs/topology.png` |")
    w("| Dataset attribution | Section 5 and `README.md` |")
    w("")
    w("## 9. Contribution statement")
    w("")
    old = os.path.join(DOCS, "REPORT.md")
    stmt = ""
    if os.path.exists(old):
        m = re.search(r"## 9\. Contribution statement\s+(.*)", open(old).read(), flags=re.S)
        if m and "**[" not in m.group(1):
            stmt = m.group(1).strip()
    w(stmt or "Individual project. **[State what you did yourself, and acknowledge any tools or assistance you used, "
              "following the course policy.]**")
    w("")

    with open(a.out, "w") as fh:
        fh.write("\n".join(L))
    left = len(re.findall(r"\*\*\[", "\n".join(L))) + ("[your name]" in "\n".join(L))
    print(f"wrote {a.out}  ({len(L)} lines, {n[0]} figures)")
    if left:
        print(f"{left} placeholder(s) still need your input: search the file for '['")
    print("Word version:  sudo apt install -y pandoc && "
          "pandoc docs/FINAL_REPORT.md --resource-path=docs -o docs/FINAL_REPORT.docx")


if __name__ == "__main__":
    main()
