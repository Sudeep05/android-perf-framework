"""
modules/start_time.py — Cold, warm and hot start measurement.

Definitions (aligned with Android Vitals):
  cold : process killed, then launched          -> am force-stop, then am start -W
  warm : process alive, activity destroyed       -> HOME, settle, then am start -W
  hot  : process alive, activity still resident   -> repeated am start -W (no HOME)

v4.1 measured "warm" as hot (it relaunched an already-foreground activity, so
WaitTime collapsed to ~0). We now background the activity with HOME between
warm runs so the activity is recreated while the process persists.
"""

import re
import time
from config import DEFAULT_COLD_WARM_RUNS


def _parse_total_time(output):
    # Prefer WaitTime (perceived), fall back to TotalTime.
    m = re.search(r"WaitTime:\s*(\d+)", output) or re.search(r"TotalTime:\s*(\d+)", output)
    return int(m.group(1)) if m else None


def measure_cold_start(adb, package, activity, runs=DEFAULT_COLD_WARM_RUNS):
    results = []
    print(f"\n  Measuring Cold Start ({runs} runs)...")
    for i in range(runs):
        adb.raw(["shell", "am", "force-stop", package])
        time.sleep(1.5)
        out = adb.shell(f"am start -W -n {package}/{activity}", timeout=30)
        t = _parse_total_time(out)
        if t is not None:
            results.append(t)
            print(f"    Run {i+1}: {t} ms")
        else:
            print(f"    Run {i+1}: FAILED to parse output")
        time.sleep(1)
    return results


def measure_warm_start(adb, package, activity, runs=DEFAULT_COLD_WARM_RUNS):
    results = []
    print(f"\n  Measuring Warm Start ({runs} runs)...")
    # Prime: ensure the process exists.
    adb.shell(f"am start -n {package}/{activity}")
    time.sleep(3)
    for i in range(runs):
        # Background the activity (process stays alive) -> true warm start.
        adb.shell("input keyevent KEYCODE_HOME")
        time.sleep(1.2)
        out = adb.shell(f"am start -W -n {package}/{activity}", timeout=30)
        t = _parse_total_time(out)
        if t is not None:
            results.append(t)
            print(f"    Run {i+1}: {t} ms")
        else:
            print(f"    Run {i+1}: FAILED to parse output")
        time.sleep(0.8)
    return results


def summarise(values):
    if not values:
        return {"min": 0, "max": 0, "avg": 0, "values": []}
    return {"min": min(values), "max": max(values),
            "avg": round(sum(values) / len(values)), "values": values}


def rate_start_time(ms, start_type="cold"):
    if start_type == "cold":
        if ms <= 1000: return "EXCELLENT"
        if ms <= 2000: return "GOOD"
        if ms <= 5000: return "ACCEPTABLE"
        return "POOR"
    else:
        if ms <= 200:  return "EXCELLENT"
        if ms <= 800:  return "GOOD"
        if ms <= 2000: return "ACCEPTABLE"
        return "POOR"
