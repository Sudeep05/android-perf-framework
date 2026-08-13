"""
modules/snapshots.py — Snapshot engine (auto + user-triggered).

Trigger file is now PER-DEVICE (passed in), so two parallel runs never consume
each other's triggers. Manual snapshot from another terminal:

    echo "after-login" > /tmp/perf_snapshot_trigger_<serial>
"""

import threading
import time
import os
import json


class SnapshotEngine:
    def __init__(self, adb, package, output_dir, trigger_file, cores=0):
        self.adb          = adb
        self.package      = package
        self.output_dir   = output_dir
        self.trigger_file = trigger_file
        self.cores        = cores
        self.snapshots    = []
        self._running     = False
        self._lock        = threading.Lock()

    # ── public API ───────────────────────────────────────────────────────
    def start(self, auto_interval_min=None):
        self._running = True
        threading.Thread(target=self._trigger_watcher, daemon=True).start()
        if auto_interval_min:
            threading.Thread(target=self._auto_snapshots,
                             args=(auto_interval_min * 60,), daemon=True).start()

        print(f"  [SnapshotEngine:{self.adb.tag}] Trigger file: {self.trigger_file}")
        print(f"  [SnapshotEngine:{self.adb.tag}] Manual snapshot (another terminal):")
        print(f'  [SnapshotEngine:{self.adb.tag}]   echo "your-label" > {self.trigger_file}')
        if auto_interval_min:
            print(f"  [SnapshotEngine:{self.adb.tag}] Auto-snapshot every {auto_interval_min} min")

    def stop(self):
        self._running = False
        if os.path.exists(self.trigger_file):
            try:
                os.remove(self.trigger_file)
            except Exception:
                pass

    def take_snapshot(self, label):
        from modules.sampling import sample_cpu_pct, parse_meminfo
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n  [Snapshot:{self.adb.tag}] Capturing '{label}' at {ts} ...")

        mem_raw = self.adb.shell(f"dumpsys meminfo {self.package}", timeout=15)
        cpu_pct, cpu_src = sample_cpu_pct(self.adb, self.package, self.cores)
        parsed = parse_meminfo(mem_raw)

        snap = {"label": label, "ts": ts, "mem_raw": mem_raw,
                "cpu_pct": cpu_pct, "cpu_src": cpu_src, "parsed": parsed}
        with self._lock:
            self.snapshots.append(snap)

        safe = label.replace(" ", "_").replace("/", "-")
        path = os.path.join(self.output_dir, f"snapshot_{safe}.txt")
        with open(path, "w") as f:
            f.write(f"=== Snapshot: {label} at {ts} ===\n\n")
            f.write(f"--- CPU ({cpu_src}, device-wide %) ---\n{cpu_pct}%\n\n")
            f.write("--- MEMINFO ---\n")
            f.write(mem_raw)

        print(f"  [Snapshot:{self.adb.tag}] saved -> {path}")
        print(f"  [Snapshot:{self.adb.tag}] PSS: {parsed.get('total_pss_mb','?')} MB "
              f"| CPU: {cpu_pct}% | GL: {parsed.get('gl_mtrack_mb','?')} MB")

    def save_summary(self):
        path = os.path.join(self.output_dir, "snapshots_summary.json")
        exportable = [{"label": s["label"], "ts": s["ts"],
                       "parsed": s["parsed"], "cpu_pct": s["cpu_pct"],
                       "cpu_src": s.get("cpu_src")} for s in self.snapshots]
        with open(path, "w") as f:
            json.dump(exportable, f, indent=2)
        return path

    # ── internals ────────────────────────────────────────────────────────
    def _trigger_watcher(self):
        while self._running:
            if os.path.exists(self.trigger_file):
                try:
                    with open(self.trigger_file) as f:
                        label = f.read().strip() or "manual"
                    os.remove(self.trigger_file)
                    self.take_snapshot(label)
                except Exception as e:
                    print(f"  [SnapshotEngine:{self.adb.tag}] Trigger error: {e}")
            time.sleep(1)

    def _auto_snapshots(self, interval_sec):
        count = 0
        while self._running:
            for _ in range(interval_sec):
                if not self._running:
                    return
                time.sleep(1)
            count += 1
            self.take_snapshot(f"auto_{count}_at_{time.strftime('%H%M%S')}")
