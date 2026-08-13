"""
modules/device.py — Device detection, profiling and suitability assessment.
Serial-aware: every device call goes through the injected ADB instance.
"""

import re
from config import MIN_RECOMMENDED, RAM_TIERS


def get_device_info(adb):
    """Collect full device profile via the serial-bound ADB instance."""
    props = {
        "model":        adb.shell("getprop ro.product.model"),
        "brand":        adb.shell("getprop ro.product.brand"),
        "manufacturer": adb.shell("getprop ro.product.manufacturer"),
        "android_ver":  adb.shell("getprop ro.build.version.release"),
        "api_level":    adb.shell("getprop ro.build.version.sdk"),
        "cpu_abi":      adb.shell("getprop ro.product.cpu.abi"),
        "hardware":     adb.shell("getprop ro.hardware"),
        "device_name":  adb.shell("getprop ro.product.device"),
        "serial":       adb.serial or adb.raw(["get-serialno"]),
    }

    # RAM
    meminfo = adb.shell("cat /proc/meminfo")
    ram_kb = 0
    for line in meminfo.splitlines():
        if line.startswith("MemTotal"):
            m = re.search(r"(\d+)", line)
            if m:
                ram_kb = int(m.group(1))
    props["ram_total_kb"] = ram_kb
    props["ram_total_gb"] = round(ram_kb / (1024 * 1024), 1)

    # CPU cores
    cores = adb.shell("nproc")
    props["cpu_cores"] = int(cores) if cores.isdigit() else 0

    # CPU max frequency (best-effort; some kernels restrict cpufreq sysfs)
    max_freq = adb.shell("cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    props["cpu_max_freq_ghz"] = round(int(max_freq) / 1_000_000, 2) if max_freq.isdigit() else 0.0

    # Storage / screen
    props["storage_raw"]    = adb.shell("df /data")
    props["screen_size"]    = adb.shell("wm size").replace("Physical size:", "").strip()
    props["screen_density"] = adb.shell("wm density").replace("Physical density:", "").strip()

    # Battery capacity
    bat_cap = adb.shell("cat /sys/class/power_supply/battery/charge_full_design 2>/dev/null || echo 0")
    try:
        props["battery_mah"] = int(bat_cap) // 1000
    except Exception:
        props["battery_mah"] = 0

    return props


def get_app_info(adb, package):
    """Version + friendly name for the target package."""
    dumpsys = adb.shell(f"dumpsys package {package}")
    info = {"package": package}
    m = re.search(r"versionName=([^\s]+)", dumpsys)
    info["version"] = m.group(1) if m else "N/A"
    m = re.search(r"versionCode=([^\s]+)", dumpsys)
    info["version_code"] = m.group(1) if m else "N/A"
    info["app_name"] = package.split(".")[-1].capitalize()
    return info


def get_main_activity(adb, package):
    """Auto-detect the main launcher activity."""
    out = adb.shell(
        f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {package}")
    for line in out.splitlines():
        if "/" in line and not line.startswith("No"):
            return line.strip().split("/")[-1]
    out2 = adb.shell(
        f"dumpsys package {package} | grep 'android.intent.action.MAIN' -A 1")
    m = re.search(r"([A-Za-z.]+Activity)", out2)
    return m.group(1) if m else "MainActivity"


def is_installed(adb, package):
    return package in adb.shell(f"pm list packages | grep {package}")


def assess_suitability(device_info):
    """Score device suitability (0-100) for running a business Android app."""
    score, issues, details = 100, [], {}

    ram_gb = device_info.get("ram_total_gb", 0)
    api    = int(device_info.get("api_level", 0) or 0)
    cores  = device_info.get("cpu_cores", 0)
    freq   = device_info.get("cpu_max_freq_ghz", 0.0)

    if ram_gb < 2:
        score -= 40
        issues.append(f"RAM {ram_gb} GB is critically low (min recommended: {MIN_RECOMMENDED['ram_gb']} GB)")
        details["ram"] = {"value": ram_gb, "status": "CRITICAL"}
    elif ram_gb < MIN_RECOMMENDED["ram_gb"]:
        score -= 20
        issues.append(f"RAM {ram_gb} GB is below recommended {MIN_RECOMMENDED['ram_gb']} GB")
        details["ram"] = {"value": ram_gb, "status": "LOW"}
    else:
        details["ram"] = {"value": ram_gb, "status": "GOOD"}

    if api < MIN_RECOMMENDED["android_api"]:
        score -= 20
        issues.append(f"Android API {api} is below min recommended API {MIN_RECOMMENDED['android_api']} (Android 8.0)")
        details["api"] = {"value": api, "status": "LOW"}
    elif api < 28:
        score -= 5
        details["api"] = {"value": api, "status": "ACCEPTABLE"}
    else:
        details["api"] = {"value": api, "status": "GOOD"}

    if cores < MIN_RECOMMENDED["cpu_cores"]:
        score -= 15
        issues.append(f"Only {cores} CPU cores — min recommended is {MIN_RECOMMENDED['cpu_cores']}")
        details["cores"] = {"value": cores, "status": "LOW"}
    else:
        details["cores"] = {"value": cores, "status": "GOOD"}

    if 0 < freq < MIN_RECOMMENDED["cpu_freq_ghz"]:
        score -= 15
        issues.append(f"CPU max frequency {freq} GHz is below recommended {MIN_RECOMMENDED['cpu_freq_ghz']} GHz")
        details["cpu_freq"] = {"value": freq, "status": "LOW"}
    else:
        details["cpu_freq"] = {"value": freq, "status": "GOOD"}

    if score >= 85:   tier = "EXCELLENT"
    elif score >= 70: tier = "GOOD"
    elif score >= 50: tier = "ACCEPTABLE"
    else:             tier = "NOT RECOMMENDED"

    ram_tier = "unknown"
    for t, (lo, hi) in RAM_TIERS.items():
        if lo <= ram_gb < hi:
            ram_tier = t
            break

    return {"score": score, "tier": tier, "ram_tier": ram_tier,
            "issues": issues, "details": details}
