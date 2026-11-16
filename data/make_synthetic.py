#!/usr/bin/env python3
"""Fallback generator: produce a CSV with the same columns as ai4i2020.csv.

Used only when the real dataset could not be downloaded. It follows the
generation recipe documented on the dataset's UCI page (type mix 50/30/20,
random-walk temperatures, torque ~ N(40, 10), speed derived from torque at roughly constant power,
tool wear +2/+3/+5 min per L/M/H part). Every record imported from this file
is labelled source=synthetic-generator.
"""
import argparse
import csv
import math
import random

COLUMNS = ["UDI", "Product ID", "Type", "Air temperature [K]", "Process temperature [K]",
           "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]", "Machine failure",
           "TWF", "HDF", "PWF", "OSF", "RNF"]


def generate(rows: int, seed: int):
    rnd = random.Random(seed)
    air_walk, proc_walk, wear = 0.0, 0.0, 0
    wear_fail_at = rnd.randint(200, 240)
    for udi in range(1, rows + 1):
        typ = rnd.choices("LMH", weights=(50, 30, 20))[0]
        air_walk = max(-2.5, min(2.5, air_walk + rnd.gauss(0, 0.05)))
        proc_walk = max(-1.2, min(1.2, proc_walk + rnd.gauss(0, 0.03)))
        air = 300 + 2 * air_walk
        proc = air + 10 + proc_walk
        torque = max(3.8, rnd.gauss(40, 10))
        rpm = int(min(2886, max(1168, 6300 / torque * 60 / (2 * math.pi) + rnd.gauss(0, 60))))
        wear += {"L": 2, "M": 3, "H": 5}[typ]
        twf = 0
        if wear >= wear_fail_at:
            twf = rnd.choice((0, 1))
            wear, wear_fail_at = 0, rnd.randint(200, 240)
        power = torque * rpm * 2 * math.pi / 60
        hdf = int(proc - air < 8.6 and rpm < 1380)
        pwf = int(power < 3500 or power > 9000)
        osf = int(wear * torque > {"L": 11000, "M": 12000, "H": 13000}[typ])
        rnf = int(rnd.random() < 0.001)
        yield [udi, f"{typ}{rnd.randint(10000, 99999)}", typ, f"{air:.1f}", f"{proc:.1f}", rpm,
               f"{torque:.1f}", wear, int(any((twf, hdf, pwf, osf, rnf))), twf, hdf, pwf, osf, rnf]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=2020)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(generate(a.rows, a.seed))
    print(f"wrote {a.rows} synthetic rows to {a.out}")
