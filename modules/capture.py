"""
modules/capture.py — Background continuous capture engine.

Runs one CPU+Memory sampling thread plus three logcat streams (gps/camera,
network/SDK, full logs). All bound to a single device via the injected ADB.

Change vs v4.1: logcat is streamed via adb WITHOUT a shell pipe, and filtering
happens in a Python reader thread. This removes the OS `grep` dependency
(works the same on macOS/Linux/Windows), the shell-injection surface, and the
"one process silently dies" failure mode of `adb logcat | grep`.
"""

import re
import threading
import time
import os


class CaptureEngine:
    def __init__(self, adb, package, output_dir, interval_sec=10):
        self.adb        = adb
        self.package    = package
        self.output_dir = output_dir
        self.interval   = interval_sec
        self._procs     = []
        self._threads   = []
        self._running   = False

    # ── public API ───────────────────────────────────────────────────────
    def start(self):
        self._running = True

        t = threading.Thread(target=self._perf_loop, daemon=True)
        t.start()
        self._threads.append(t)

        # NOTE: labels MUST match output_files() keys/filenames — the network
        # analyser reads network_calls.txt / app_logs.txt by those exact names.
        self._start_logcat("gps_camera_logs",
            r"camera|gps|location|GPS_PROVIDER|fused|LocationManager")
        self._start_logcat("network_calls",
            r"okhttp|retrofit|http|api|WorkManager|PlayCore|Firebase|JobScheduler")
        self._start_logcat("app_logs", None, threadtime=True)

        print(f"  [CaptureEngine:{self.adb.tag}] All captures started.")

    def stop(self):
        self._running = False
        for proc in self._procs:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=2)
        print(f"  [CaptureEngine:{self.adb.tag}] All captures stopped.")

    def output_files(self):
        j = lambda n: os.path.join(self.output_dir, n)
        return {
            "perf_stats":      j("perf_stats.txt"),
            "gps_camera_logs": j("gps_camera_logs.txt"),
            "network_calls":   j("network_calls.txt"),
            "app_logs":        j("app_logs.txt"),
        }

    # ── internals ────────────────────────────────────────────────────────
    def _perf_loop(self):
        from modules.sampling import sample_cpu_pct
        filepath = os.path.join(self.output_dir, "perf_stats.txt")
        while self._running:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                cpu_pct, src = sample_cpu_pct(self.adb, self.package)
                mem_out = self.adb.shell(f"dumpsys meminfo {self.package}", timeout=8)
                mem_lines = [l.strip() for l in mem_out.splitlines()
                             if any(k in l for k in ("TOTAL", "Native Heap", "Dalvik Heap",
                                                     "GL mtrack", "Java Heap", "Graphics"))]
                with open(filepath, "a") as f:
                    f.write(f"\n=== {ts} ===\n")
                    f.write(f"--- CPU ({src}, device-wide %) ---\n")
                    f.write(f"{cpu_pct}%\n")
                    f.write("--- MEMORY ---\n")
                    f.write("\n".join(mem_lines) + "\n")
            except Exception as e:
                with open(filepath, "a") as f:
                    f.write(f"=== {ts} === ERROR: {e}\n")

            # Sleep in small slices so stop() is responsive.
            for _ in range(self.interval):
                if not self._running:
                    break
                time.sleep(1)

    def _start_logcat(self, label, pattern, threadtime=False):
        filepath = os.path.join(self.output_dir, f"{label}.txt")
        args = ["logcat"] + (["-v", "threadtime"] if threadtime else [])
        proc = self.adb.stream(args)
        self._procs.append(proc)
        rx = re.compile(pattern, re.IGNORECASE) if pattern else None

        def _reader():
            with open(filepath, "w") as out:
                try:
                    for line in proc.stdout:
                        if not self._running:
                            break
                        if rx is None or rx.search(line):
                            out.write(line)
                            out.flush()
                except Exception:
                    pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        self._threads.append(t)
