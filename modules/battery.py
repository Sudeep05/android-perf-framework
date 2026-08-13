"""
modules/battery.py — Battery stats capture and parsing (serial-aware).

The USB problem: a device tethered for adb is charging, so `was_charging` is
almost always true and v4.1 voided all drain figures. We add the standard
work-around:

    dumpsys battery unplug        # tell the battery service it's on battery
    ... run the session ...
    dumpsys battery reset         # restore real charging state

`unplug` makes batterystats accrue on-battery events (screen/CPU/GPS/camera
drain accounting) even while physically tethered. It does NOT physically stop
charging, so absolute mAh drain is still approximate — for true physical drain
use wireless adb (`adb tcpip` / pairing). The report labels this accordingly.
"""

import re
import os


def reset_batterystats(adb):
    adb.shell("dumpsys batterystats --reset")


def set_simulated_unplug(adb):
    """Report the device as on-battery for stats purposes. Returns True if applied."""
    adb.shell("dumpsys battery unplug")
    # Belt-and-braces on OEMs where `unplug` alone doesn't flip the source.
    adb.shell("dumpsys battery set ac 0")
    adb.shell("dumpsys battery set usb 0")
    status = adb.shell("dumpsys battery | grep -i 'AC powered\\|USB powered'")
    return "false" in status.lower() if status else True


def reset_battery_state(adb):
    """Restore real charging state — ALWAYS call this at session end."""
    adb.shell("dumpsys battery reset")


def capture_battery_stats(adb, output_dir):
    stats_path = os.path.join(output_dir, "battery_stats.txt")
    print(f"  [Battery:{adb.tag}] Capturing battery stats...")
    out = adb.shell("dumpsys batterystats", timeout=30)
    with open(stats_path, "w") as f:
        f.write(out)
    print(f"  [Battery:{adb.tag}] Stats saved -> {stats_path}")
    return stats_path


def capture_bugreport(adb, output_dir):
    zip_path = os.path.join(output_dir, "bugreport.zip")
    print(f"  [Battery:{adb.tag}] Capturing bugreport (2-3 min)...")
    r = adb.raw_cp(["bugreport", zip_path], timeout=300)
    if os.path.exists(zip_path):
        print(f"  [Battery:{adb.tag}] Bugreport saved -> {zip_path}")
        return zip_path
    print(f"  [Battery:{adb.tag}] Bugreport failed: {getattr(r,'stderr','')[:200]}")
    return None


def parse_battery_stats(stats_path, simulated_unplug=False):
    try:
        with open(stats_path, "r", errors="replace") as f:
            content = f.read()
    except Exception:
        return {}

    result = {"simulated_unplug": simulated_unplug}

    m = re.search(r"Total run time:\s*([\d\w\s]+)", content)
    result["session_duration"] = m.group(1).strip() if m else "unknown"

    m = re.search(r"status=(\w+)", content)
    physically_charging = (m.group(1) == "charging") if m else False
    # If we simulated unplug, drain accounting is valid regardless of physical state.
    result["was_charging"] = physically_charging and not simulated_unplug

    m = re.search(r"Estimated battery capacity:\s*([\d,]+)\s*mAh", content)
    result["battery_capacity_mah"] = int(m.group(1).replace(",", "")) if m else 0

    m = re.search(r"charge=(\d+)", content)
    result["charge_start_mah"] = int(m.group(1)) if m else 0

    temps = re.findall(r"temp=(\d+)", content)
    if temps:
        readings = [round(int(t) / 10, 1) for t in temps]
        result["temp_readings_c"] = readings
        result["temp_max_c"] = max(readings)
        result["temp_min_c"] = min(readings)
    else:
        result["temp_readings_c"] = []
        result["temp_max_c"] = 0
        result["temp_min_c"] = 0

    result["camera_sessions"] = len(re.findall(r"\+\S+.*?\+camera", content))
    result["gps_activations"] = len(re.findall(r"\+\S+.*?\+gps", content))
    result["camera_total_sec"] = _hw_time(content, "camera")
    result["gps_total_sec"] = _hw_time(content, "gps")
    result["workmanager_jobs"] = len(re.findall(r"\+job=.*?SystemJobService", content))
    result["firebase_jobs"] = len(re.findall(r"\+job=.*?datatransport", content))
    result["wifi_wakeups"] = len(re.findall(r"wakeupap=.*?:", content))

    # These markers are OEM/version-dependent — flag as indicative, not authoritative.
    result["hw_counts_indicative"] = True
    return result


def _time_to_sec(ts):
    total = 0
    for unit, mult in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        mm = re.search(rf"(\d+){unit}", ts)
        if mm:
            total += int(mm.group(1)) * mult
    return total


def _hw_time(content, hw):
    total, on_time = 0, None
    for line in content.split("\n"):
        t_match = re.match(r"\s+\+(\S+)", line)
        if t_match:
            current = _time_to_sec(t_match.group(1))
            if f"+{hw}" in line:
                on_time = current
            elif f"-{hw}" in line and on_time is not None:
                total += current - on_time
                on_time = None
    return total
