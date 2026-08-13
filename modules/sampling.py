"""
modules/sampling.py — single source of truth for CPU + memory sampling.

Both the continuous CaptureEngine and the SnapshotEngine call these, so a
report never shows two different parsers disagreeing about the same device.

Why not `top -n 1 -b` for CPU?
  top's column order and %CPU index vary across toybox/OEM builds, and its
  %CPU is PER CORE (a 4-core device reads up to 400%), which silently
  mis-rates against a 0-100 benchmark. We use `dumpsys cpuinfo` as primary:
  its per-process percentage is already relative to total device capacity.
  top is kept only as a normalized fallback.
"""

import re


# ── CPU ──────────────────────────────────────────────────────────────────────
def sample_cpu_pct(adb, package, cores=0):
    """
    Return (cpu_pct_of_device, source) where cpu_pct_of_device is 0-100 across
    the whole SoC. `source` is 'cpuinfo' or 'top' for provenance in the report.
    """
    # Primary: dumpsys cpuinfo — line like "  12% 1234/com.example.app: 8% ..."
    raw = adb.shell("dumpsys cpuinfo", timeout=8)
    if raw:
        pat = re.compile(r"([\d.]+)%\s+\d+/" + re.escape(package) + r"\b")
        best = None
        for m in pat.finditer(raw):
            v = float(m.group(1))
            best = v if best is None else max(best, v)
        if best is not None:
            return round(best, 1), "cpuinfo"

    # Fallback: top, parsed by header, normalized by core count.
    top = adb.shell("top -n 1 -b", timeout=8) or adb.shell("top -n 1", timeout=8)
    pct = _parse_top_cpu(top, package, cores)
    return pct, "top"


def _parse_top_cpu(top_out, package, cores):
    if not top_out:
        return 0.0
    lines = top_out.splitlines()
    # Locate the header row to find the %CPU and CMD/ARGS columns dynamically.
    cpu_idx = cmd_idx = None
    for i, line in enumerate(lines):
        up = line.upper()
        if ("PID" in up) and ("CPU" in up) and ("ARGS" in up or "CMD" in up or "NAME" in up):
            cols = line.split()
            for j, c in enumerate(cols):
                cu = c.upper().strip("[]%")
                if cu in ("CPU", "%CPU") and cpu_idx is None:
                    cpu_idx = j
                if cu in ("ARGS", "CMD", "NAME", "COMMAND") and cmd_idx is None:
                    cmd_idx = j
            body = lines[i + 1:]
            break
    else:
        cpu_idx, body = 8, lines  # last-resort legacy index

    short = package.split(".")[-1]
    for line in body:
        if package in line or short in line:
            parts = line.split()
            if cpu_idx is not None and cpu_idx < len(parts):
                try:
                    per_core = float(parts[cpu_idx].strip("%"))
                    # top is per-core; convert to device-wide 0-100.
                    return round(per_core / cores, 1) if cores else round(per_core, 1)
                except ValueError:
                    continue
    return 0.0


# ── Memory ───────────────────────────────────────────────────────────────────
def _find(raw, pattern):
    m = re.search(pattern, raw)
    return int(m.group(1)) if m else None


def parse_meminfo(raw):
    """
    Label-driven parse of `dumpsys meminfo <pkg>`. Prefers the stable App Summary
    labels (Android 8+), falls back to the detailed process table. Never relies
    on positional column indices for totals.
    """
    result = {}

    # App Summary (label form) — stable across modern Android.
    java   = _find(raw, r"Java Heap:\s*(\d+)")
    native = _find(raw, r"Native Heap:\s*(\d+)")
    graph  = _find(raw, r"Graphics:\s*(\d+)")

    # Totals: prefer "TOTAL PSS:" label; else the table row "TOTAL  <pss> ...".
    total_pss = _find(raw, r"TOTAL PSS:\s*(\d+)")
    if total_pss is None:
        m = re.search(r"^\s*TOTAL\b[^\d]*?(\d+)", raw, re.MULTILINE)
        total_pss = int(m.group(1)) if m else None
    swap = _find(raw, r"TOTAL SWAP PSS:\s*(\d+)")

    # Detailed table rows (positional but only for optional extras).
    dalvik = None
    m = re.search(r"Dalvik Heap\s+(\d+)", raw)
    if m:
        dalvik = int(m.group(1))
    gl_mtrack = None
    m = re.search(r"GL mtrack\s+(\d+)", raw)
    if m:
        gl_mtrack = int(m.group(1))

    def mb(kb):
        return round(kb / 1024, 1) if kb is not None else None

    if native is not None:
        result["native_heap_pss_kb"] = native
        result["native_heap_mb"] = mb(native)
    if dalvik is not None:
        result["dalvik_heap_pss_kb"] = dalvik
        result["dalvik_heap_mb"] = mb(dalvik)
    if java is not None:
        result["java_heap_kb"] = java
    if graph is not None:
        result["graphics_kb"] = graph
        result["graphics_mb"] = mb(graph)
    # GL mtrack: prefer table value, else approximate from Graphics summary.
    gl = gl_mtrack if gl_mtrack is not None else graph
    if gl is not None:
        result["gl_mtrack_kb"] = gl
        result["gl_mtrack_mb"] = mb(gl)
    if total_pss is not None:
        result["total_pss_kb"] = total_pss
        result["total_pss_mb"] = mb(total_pss)
    result["swap_pss_kb"] = swap or 0
    result["swap_pss_mb"] = mb(swap or 0)

    return result
