#!/usr/bin/env python3
"""Turn the raw evidence files into tables, charts and evidence/results.md.

    python experiments/make_report.py                      # everything
    python experiments/make_report.py --section performance
    python experiments/make_report.py --section recovery

Every number is computed from files written by the experiment scripts:
  evidence/E_performance/<label>_{ping.txt,iperf.json,bench.csv,alerts.csv}
  evidence/F_recovery/{monitor.csv,watchdog.log}   evidence/events.log
"""
import argparse
import csv
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVID = os.path.join(ROOT, "evidence")
PERF = os.path.join(EVID, "E_performance")
RECO = os.path.join(EVID, "F_recovery")
LABELS = ["baseline", "delay", "loss", "rate", "recovered"]
OPS = [("write", "Write reading (POST, keep-alive)"),
       ("read_latest", "Read latest state (GET, keep-alive)"),
       ("read_history", "Read 200 readings (GET, keep-alive)"),
       ("newconn_read", "Read with new TCP+TLS connection")]


def pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def f(x, nd=1):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ performance ---
def load_condition(label):
    d = {"label": label}
    p = os.path.join(PERF, f"{label}_bench.csv")
    if not os.path.exists(p):
        return None
    with open(p, newline="") as fh:
        rows = list(csv.DictReader(fh))
    d["requests"] = len(rows)
    d["errors"] = sum(1 for r in rows if r["ok"] != "1")
    d["ops"] = {}
    for op, _ in OPS:
        sel = [r for r in rows if r["op"] == op]
        good = [r for r in sel if r["ok"] == "1"]
        tot = [float(r["total_ms"]) for r in good]
        d["ops"][op] = {"n": len(sel), "errors": len(sel) - len(good),
                        "p50": pct(tot, 50), "p95": pct(tot, 95), "p99": pct(tot, 99),
                        "app": pct([float(r["app_ms"]) for r in good], 50),
                        "db": pct([float(r["db_ms"]) for r in good], 50),
                        "net": pct([float(r["net_ms"]) for r in good], 50)}
    if rows:
        t0 = min(float(r["t_start"]) for r in rows)
        t1 = max(float(r["t_start"]) + float(r["total_ms"]) / 1000 for r in rows)
        d["req_per_s"] = (len(rows) - d["errors"]) / max(t1 - t0, 1e-9)

    d["rtt_avg"] = d["rtt_mdev"] = d["ping_loss"] = None
    p = os.path.join(PERF, f"{label}_ping.txt")
    if os.path.exists(p):
        txt = open(p).read()
        m = re.search(r"([\d.]+)% packet loss", txt)
        d["ping_loss"] = float(m.group(1)) if m else None
        m = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", txt)
        if m:
            d["rtt_avg"], d["rtt_mdev"] = float(m.group(2)), float(m.group(4))

    d["mbps"] = d["retrans"] = None
    p = os.path.join(PERF, f"{label}_iperf.json")
    if os.path.exists(p):
        try:
            j = json.load(open(p))
            d["mbps"] = j["end"]["sum_received"]["bits_per_second"] / 1e6
            d["retrans"] = j["end"]["sum_sent"].get("retransmits")
        except (ValueError, KeyError):
            pass

    d["alert_n"], d["alert_p50"], d["alert_p95"], d["uplink_p50"] = 0, None, None, None
    p = os.path.join(PERF, f"{label}_alerts.csv")
    if os.path.exists(p):
        with open(p, newline="") as fh:
            al = [r for r in csv.DictReader(fh) if r["machine_id"].startswith("B")]
        dl = [float(r["delivery_ms"]) for r in al]
        d["alert_n"] = len(al)
        if dl:
            d["alert_p50"], d["alert_p95"] = pct(dl, 50), pct(dl, 95)
            d["uplink_p50"] = pct([float(r["uplink_ms"]) for r in al], 50)
    return d


def condition_note(label):
    p = os.path.join(PERF, f"{label}_meta.txt")
    if label in ("baseline", "recovered"):
        return "no impairment"
    if not os.path.exists(p):
        return ""
    txt = open(p).read()
    m = re.search(r"netem.*?(delay [\d.]+m?s(?:\s+[\d.]+m?s)?|loss [\d.]+%)", txt)
    if m:
        return "netem " + m.group(1) + " per direction"
    m = re.search(r"tbf .*?rate (\S+)", txt)
    if m:
        return f"tbf rate {m.group(1)} per direction"
    m = re.search(r"mod 1000 < (\d+)", txt)
    if m:
        return f"nftables random drop {int(m.group(1)) / 10:g}% per direction"
    return ""


def performance_md(conds):
    L = []
    L.append("| Condition | Impairment | RTT avg (ms) | RTT mdev (ms) | Ping loss | TCP throughput (Mbit/s) | TCP retransmits | Requests OK | Requests/s |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for c in conds:
        ok = c["requests"] - c["errors"]
        L.append(f"| {c['label']} | {condition_note(c['label'])} | {f(c['rtt_avg'], 2)} | {f(c['rtt_mdev'], 2)} | "
                 f"{f(c['ping_loss'], 0)}% | {f(c['mbps'], 1)} | {c['retrans'] if c['retrans'] is not None else 'n/a'} | "
                 f"{ok}/{c['requests']} | {f(c.get('req_per_s'), 1)} |")
    L.append("")
    L.append("Application latency per operation (ms; successful requests only):")
    L.append("")
    L.append("| Operation | Condition | n | errors | p50 | p95 | p99 | of p50: network | API processing | Redis |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for op, title in OPS:
        for c in conds:
            o = c["ops"][op]
            L.append(f"| {title} | {c['label']} | {o['n']} | {o['errors']} | {f(o['p50'])} | {f(o['p95'])} | {f(o['p99'])} | "
                     f"{f(o['net'])} | {f(max(o['app'] - o['db'], 0) if o['app'] == o['app'] else None, 2)} | {f(o['db'], 2)} |")
    L.append("")
    L.append("Alert delivery delay: sensor timestamp on the plant floor to first sight by the operations zone (ms):")
    L.append("")
    L.append("| Condition | alerts | uplink p50 (plant to API) | delivery p50 | delivery p95 |")
    L.append("|---|---:|---:|---:|---:|")
    for c in conds:
        L.append(f"| {c['label']} | {c['alert_n']} | {f(c['uplink_p50'])} | {f(c['alert_p50'])} | {f(c['alert_p95'])} |")
    return "\n".join(L)


def performance_findings(conds):
    by = {c["label"]: c for c in conds}
    base = by.get("baseline")
    out = []
    if not base:
        return out
    bw = base["ops"]["write"]
    for lab in ("delay", "loss", "rate"):
        c = by.get(lab)
        if not c:
            continue
        w = c["ops"]["write"]
        nc, bnc = c["ops"]["newconn_read"], base["ops"]["newconn_read"]
        h, bh = c["ops"]["read_history"], base["ops"]["read_history"]
        s = (f"**{lab}** ({condition_note(lab)}): write p50 {f(bw['p50'])} -> {f(w['p50'])} ms and p95 "
             f"{f(bw['p95'])} -> {f(w['p95'])} ms, while server-side time stayed at {f(w['app'], 2)} ms "
             f"(baseline {f(bw['app'], 2)} ms) with Redis at {f(w['db'], 2)} ms. "
             f"New-connection reads went {f(bnc['p50'])} -> {f(nc['p50'])} ms; "
             f"200-reading history reads {f(bh['p50'])} -> {f(h['p50'])} ms. "
             f"TCP throughput {f(base['mbps'], 1)} -> {f(c['mbps'], 1)} Mbit/s"
             + (f", retransmits {base['retrans']} -> {c['retrans']}" if c["retrans"] is not None else "")
             + f". Alert delivery p50 {f(base['alert_p50'])} -> {f(c['alert_p50'])} ms. "
             f"Errors: {c['errors']} of {c['requests']} requests.")
        out.append(s)
    r = by.get("recovered")
    if r:
        rw = r["ops"]["write"]
        out.append(f"**recovered**: with the impairment removed, write p50 is {f(rw['p50'])} ms "
                   f"(baseline {f(bw['p50'])} ms) and RTT {f(r['rtt_avg'], 2)} ms (baseline {f(base['rtt_avg'], 2)} ms).")
    return out


# --------------------------------------------------------------- recovery ---
def load_events():
    p = os.path.join(EVID, "events.log")
    ev = []
    if os.path.exists(p):
        for line in open(p):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3:
                ev.append((float(parts[0]), parts[2]))
    return ev


def recovery_analysis():
    mp = os.path.join(RECO, "monitor.csv")
    if not os.path.exists(mp):
        return None
    with open(mp, newline="") as fh:
        mon = [(float(r["epoch"]), r["ok"] == "1", int(r["status"]), float(r["latency_ms"]), r["error"])
               for r in csv.DictReader(fh)]
    if not mon:
        return None
    t_first, t_last = mon[0][0], mon[-1][0]
    ev = [e for e in load_events() if t_first - 5 <= e[0] <= t_last + 5]
    wd = []
    wp = os.path.join(RECO, "watchdog.log")
    if os.path.exists(wp):
        for line in open(wp):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3:
                wd.append((float(parts[0]), parts[2]))
    faults = [(t, m.split()[1]) for t, m in ev if m.startswith("FAULT_INJECT")]
    res = []
    for i, (tf, name) in enumerate(faults):
        t_next = faults[i + 1][0] if i + 1 < len(faults) else t_last + 1
        win = [m for m in mon if tf <= m[0] < t_next]
        fails = [m for m in win if not m[1]]
        row = {"name": name, "t_fault": tf, "failed_probes": len(fails), "probes": len(win),
               "symptom": "", "first_fail_s": None, "detect_s": None, "outage_s": None, "action": ""}
        if fails:
            row["first_fail_s"] = fails[0][0] - tf
            # a probe counts as "restored" at the moment its successful answer arrived
            after = [m for m in win if m[1] and m[0] > fails[-1][0]]
            if after:
                row["outage_s"] = after[0][0] + after[0][3] / 1000.0 - tf
            kinds = sorted({(f"HTTP {m[2]}" if m[2] else m[4]) for m in fails})
            row["symptom"] = ", ".join(kinds)
        det = [t for t, m in wd if tf <= t < t_next and m.startswith("DETECTED")]
        if det:
            row["detect_s"] = det[0] - tf
        acts = [m.replace("ACTION ", "") for t, m in wd if tf <= t < t_next and m.startswith("ACTION")]
        row["action"] = "; ".join(acts)
        res.append(row)
    ok = sum(1 for m in mon if m[1])
    return {"faults": res, "probes": len(mon), "ok": ok, "availability": 100.0 * ok / len(mon),
            "duration_s": t_last - t_first, "monitor": mon, "events": ev,
            "healthy_p50": pct([m[3] for m in mon if m[1]], 50)}


def recovery_md(ra):
    L = ["| Fault | Symptom seen by the probe | First failed probe after (s) | Watchdog detected after (s) | Service restored after (s) | Failed probes | Recovery action |",
         "|---|---|---:|---:|---:|---:|---|"]
    for r in ra["faults"]:
        L.append(f"| {r['name']} | {r['symptom']} | {f(r['first_fail_s'])} | {f(r['detect_s'])} | {f(r['outage_s'])} | "
                 f"{r['failed_probes']} | {r['action']} |")
    L.append("")
    L.append(f"Health probe: {ra['probes']} probes over {ra['duration_s']:.0f} s (one every 0.5 s, 1.5 s timeout), "
             f"{ra['ok']} successful = {ra['availability']:.1f}% availability during the experiment; "
             f"median healthy probe latency {f(ra['healthy_p50'])} ms.")
    return "\n".join(L)


# ----------------------------------------------------------------- charts ---
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
BLUE, ORANGE, AQUA, CRITICAL = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def charts(conds, ra):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - skipping charts")
        return []
    plt.rcParams["font.family"] = "DejaVu Sans"
    made = []

    if conds:
        labels = [c["label"] for c in conds]
        fig, axes = plt.subplots(1, len(OPS), figsize=(3.4 * len(OPS), 3.9), facecolor=SURFACE)
        for ax, (op, title) in zip(axes, OPS):
            _style(ax)
            p50 = [c["ops"][op]["p50"] for c in conds]
            p95 = [c["ops"][op]["p95"] for c in conds]
            x = range(len(conds))
            ax.bar(x, p50, width=0.56, color=BLUE, edgecolor=SURFACE, linewidth=2, label="p50")
            ax.scatter(x, p95, marker="_", s=260, color=INK, linewidths=1.6, zorder=3, label="p95")
            top = max([v for v in p95 + p50 if v == v] or [1])
            for i, v in enumerate(p50):
                if v == v:
                    # keep the value label clear of the p95 tick when the two are close
                    near = p95[i] == p95[i] and 0 <= p95[i] - v < top * 0.09
                    ybase = p95[i] if near else v
                    ax.text(i, ybase + top * 0.02, f"{v:.1f}", ha="center", va="bottom", fontsize=8, color=INK2)
            ax.set_ylim(0, top * 1.15)
            ax.set_xticks(list(x))
            ax.set_xticklabels(labels, fontsize=8.5, color=INK2)
            ax.set_title(title, fontsize=9.5, color=INK, loc="left", pad=10)
        axes[0].set_ylabel("latency (ms)", color=INK2, fontsize=9)
        axes[-1].legend(frameon=False, fontsize=8.5, labelcolor=INK2, loc="upper right")
        fig.suptitle("Request latency by network condition: median (bar) and 95th percentile (tick), identical workload",
                     x=0.01, ha="left", fontsize=11.5, color=INK)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        p = os.path.join(EVID, "chart_latency_by_condition.png")
        fig.savefig(p, dpi=150, facecolor=SURFACE)
        plt.close(fig)
        made.append(p)

        fig, ax = plt.subplots(figsize=(8.6, 0.62 * len(conds) + 1.7), facecolor=SURFACE)
        _style(ax)
        ax.yaxis.grid(False)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        y = list(range(len(conds)))[::-1]
        net = [max(c["ops"]["write"]["net"], 0) for c in conds]
        db = [c["ops"]["write"]["db"] for c in conds]
        apponly = [max(c["ops"]["write"]["app"] - c["ops"]["write"]["db"], 0) for c in conds]
        left = [0.0] * len(conds)
        for vals, col, name in ((net, BLUE, "Network + TLS (total - server time)"),
                                (apponly, ORANGE, "API processing"), (db, AQUA, "Redis round trip")):
            ax.barh(y, vals, left=left, height=0.5, color=col, edgecolor=SURFACE, linewidth=2, label=name)
            left = [a + b for a, b in zip(left, vals)]
        for yi, tot in zip(y, left):
            ax.text(tot + max(left) * 0.012, yi, f"{tot:.1f} ms", va="center", fontsize=8.5, color=INK2)
        ax.set_xlim(0, max(left) * 1.14)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, color=INK2, fontsize=9.5)
        ax.set_xlabel("median time per write request (ms)", color=INK2, fontsize=9)
        ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.32))
        ax.set_title("Where the time goes for one telemetry write (median)", loc="left", fontsize=11.5, color=INK, pad=10)
        fig.tight_layout()
        p = os.path.join(EVID, "chart_time_breakdown.png")
        fig.savefig(p, dpi=150, facecolor=SURFACE)
        plt.close(fig)
        made.append(p)

    if ra:
        mon = ra["monitor"]
        t0 = mon[0][0]
        fig, ax = plt.subplots(figsize=(11, 3.9), facecolor=SURFACE)
        _style(ax)
        seg_x, seg_y = [], []
        for m in mon:                                  # break the line at failed probes
            if m[1]:
                seg_x.append(m[0] - t0)
                seg_y.append(m[3])
            else:
                seg_x.append(float("nan"))
                seg_y.append(float("nan"))
        okl = [m[3] for m in mon if m[1]] or [1]
        top = max(pct(okl, 90) * 3.0, 20.0)            # robust scale: one slow probe must not flatten the line
        clipped = [(m[0] - t0, m[3]) for m in mon if m[1] and m[3] > top * 0.8]
        seg_y = [min(v, top * 0.8) if v == v else v for v in seg_y]
        ax.plot(seg_x, seg_y, color=BLUE, linewidth=2, label="successful health probe: latency")
        for cx, cv in clipped:                         # off-scale probes: marked and labelled with their value
            ax.scatter([cx], [top * 0.8], marker="^", s=48, color=BLUE, zorder=3)
            ax.text(cx, top * 0.83, f"{cv:.0f} ms", ha="center", va="bottom", fontsize=8, color=INK2)
        fx = [m[0] - t0 for m in mon if not m[1]]
        ax.scatter(fx, [top * 0.04] * len(fx), marker="x", s=42, color=CRITICAL, linewidths=1.8, zorder=3,
                   label="failed health probe")
        level = 0
        for t, msg in ra["events"]:
            if msg.startswith(("FAULT_INJECT", "SERVICE_RESTORED")):
                kind, name = msg.split()[0], msg.split()[1]
                ax.axvline(t - t0, color=MUTED, linewidth=1, linestyle=(0, (3, 3)))
                txt = ("fault: " if kind == "FAULT_INJECT" else "restored: ") + name
                ax.text(t - t0 + 0.25, top * (1.0 - 0.07 * (level % 2)), txt, fontsize=8.5, color=INK2, va="top")
                level += 1
        ax.set_ylim(0, top * 1.02)
        ax.set_xlabel("seconds since the experiment started", color=INK2, fontsize=9)
        ax.set_ylabel("probe latency (ms)", color=INK2, fontsize=9)
        ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
        ax.set_title("Failure and recovery timeline seen from the operations zone (GET /health every 0.5 s)",
                     loc="left", fontsize=11.5, color=INK, pad=10)
        fig.tight_layout()
        p = os.path.join(EVID, "chart_recovery_timeline.png")
        fig.savefig(p, dpi=150, facecolor=SURFACE)
        plt.close(fig)
        made.append(p)
    return made


# ------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", choices=["all", "performance", "recovery"], default="all")
    a = ap.parse_args()

    conds = [c for c in (load_condition(l) for l in LABELS) if c]
    ra = recovery_analysis()

    if a.section == "performance":
        print(performance_md(conds) if conds else "no performance data yet")
        return
    if a.section == "recovery":
        print(recovery_md(ra) if ra else "no recovery data yet")
        return

    made = charts(conds, ra)
    L = ["# PlantWatch - measured results", "",
         f"Generated {time.strftime('%Y-%m-%d %H:%M:%S %z')} by `experiments/make_report.py` from the raw files in `evidence/`.",
         "All figures below are measurements from this machine; nothing is typed in by hand.", ""]
    L += ["## State 1 and 2: baseline versus degraded network", ""]
    if conds:
        L += ["Method: for each condition the same script (`experiments/measure.sh`) runs 50 pings (plant to API), "
              "a 5 s iperf3 TCP test, and `client/bench.py` (100 writes, 100 state reads, 50 history reads on one "
              "keep-alive TLS connection, then 30 reads each on a new TCP+TLS connection; fixed seed). "
              "Impairments are applied on the WAN link between the two routers, in both directions.", "",
              performance_md(conds), ""]
        if any("chart_latency" in m for m in made):
            L += ["![Latency by condition](chart_latency_by_condition.png)", "",
                  "![Time breakdown](chart_time_breakdown.png)", ""]
        fnd = performance_findings(conds)
        if fnd:
            L += ["### What the numbers show", ""] + [f"- {s}" for s in fnd] + [""]
        missing = [l for l in ("delay", "loss", "rate") if l not in [c["label"] for c in conds]]
        if missing:
            L += [f"Not measured on this machine: {', '.join(missing)} (see `evidence/E_performance/*_SKIPPED.txt`).", ""]
    else:
        L += ["No performance data yet. Run `sudo make E`.", ""]
    L += ["## State 3: failure and recovery", ""]
    if ra:
        L += ["Method: `experiments/F_recovery.sh` injects three faults while `ops/monitor.py` probes `/health` "
              "from the operations zone and `ops/watchdog.sh` (1 s probe, 3 consecutive failures) repairs the system. "
              "Times are measured from the moment of fault injection.", "", recovery_md(ra), ""]
        if any("chart_recovery" in m for m in made):
            L += ["![Recovery timeline](chart_recovery_timeline.png)", ""]
    else:
        L += ["No recovery data yet. Run `sudo make F`.", ""]
    out = os.path.join(EVID, "results.md")
    with open(out, "w") as fh:
        fh.write("\n".join(L))
    print(f"wrote {out}" + "".join(f"\nwrote {m}" for m in made))


if __name__ == "__main__":
    main()
