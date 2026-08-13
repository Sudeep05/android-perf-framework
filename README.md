# Android Mobile Performance Testing Framework — v4.2
## Performance Engineering CoE

An **observer** framework: it profiles the device, measures start times, and
continuously captures CPU/memory/GPS/camera/network/battery while *you* — or an
external UI-automation driver (Appium / Maestro / monkey / manual) — exercise
the app. It then produces a colour-coded Word report with optional LLM analysis.

v4.2 makes it serial-aware, runnable unattended, and parallel across devices.

---

### What changed from v4.1 (architect notes)

| Area | v4.1 | v4.2 |
|------|------|------|
| Device targeting | bare `adb shell` (breaks with >1 device) | every call routed through a serial-bound `ADB` object (`core/adb.py`) |
| Multi-device | one run, one device, shared `/tmp` trigger | `run_parallel.py` fans out; **per-serial** trigger files and output dirs |
| Automation | blocking `input()` gates only | `--duration` unattended mode; CLI + `--config` JSON; `input()` only when interactive |
| Session duration | `getmtime(session_dir)` (always ~1 min — bug) | anchored to `started_epoch` recorded at session start |
| Warm start | relaunched a foreground activity (was really *hot* start) | backgrounds via `HOME` between runs → true warm start |
| CPU sampling | positional `top` index, per-core, unnormalized | `dumpsys cpuinfo` (device-wide %), header-aware `top` fallback normalized by cores |
| Memory parse | positional column indices (fragile on Android 11+) | label-driven App-Summary parse with table fallback (`modules/sampling.py`) |
| logcat capture | `adb logcat \| grep` (OS grep dep, silent death) | in-process regex filter on a no-shell adb stream |
| Battery over USB | `was_charging` → drain always voided | `dumpsys battery unplug` before, `reset` after (in `finally`) |
| logcat filenames | mismatched what the network analyser read | aligned to `output_files()` keys |

---

### Quick start

```bash
pip3 install python-docx --break-system-packages

# LLM key (optional — report still generates without it)
export ANTHROPIC_API_KEY=sk-ant-...        # or GEMINI_API_KEY / OPENAI_API_KEY
export PERF_LLM_PROVIDER=anthropic         # anthropic | gemini | openai

# Connect device(s) with USB Debugging enabled
cd perf_framework
```

**Interactive (single device, prompts):**
```bash
python3 framework.py
```

**Unattended (headless / CI / alongside your automation):**
```bash
python3 framework.py --package com.example.app --duration 30 --serial RZ8N1234
python3 framework.py --config runs/session.json
```

**Parallel across every connected device:**
```bash
python3 run_parallel.py --package com.example.app --duration 30
python3 run_parallel.py --config runs/session.json --serials RZ8N1234,RF9X5678
```

---

### Manual snapshot trigger (per device)

Trigger files are now namespaced by serial so parallel runs never collide:
```bash
echo "after-login"  > /tmp/perf_snapshot_trigger_RZ8N1234
echo "camera-open"  > /tmp/perf_snapshot_trigger_RZ8N1234
```
The exact path for a run is printed at startup and stored in `session_config.json`.

---

### `--config` JSON (unattended)

```json
{
  "package": "com.example.app",
  "duration_min": 30,
  "snap_mode": 1,
  "auto_interval_min": 5,
  "cold_warm_runs": 3,
  "simulate_unplug": true,
  "use_llm": true,
  "llm_provider": "anthropic"
}
```
Precedence (low → high): **defaults < JSON config < environment < CLI flags**.

---

### Battery measurement over USB

A tethered device is charging, which normally voids drain accounting. By default
v4.2 runs `dumpsys battery unplug` (reporting on-battery state for stats) and
restores real state with `dumpsys battery reset` in a `finally` block. This makes
drain **accounting** valid; absolute mAh is still approximate because the cell is
physically charging. For true physical drain, use wireless adb
(`adb tcpip 5555` / pairing) and pass `--no-unplug`.

---

### Output

`~/Desktop/PerfFramework_Output/<app>_<serial>_<timestamp>/`

```
PerfReport_<app>_<ts>.docx     ← Word report (10 sections, colour-coded)
perf_stats.txt                 ← CPU (device-wide %) + memory timeline
snapshot_*.txt                 ← individual labelled snapshots
snapshots_summary.json         ← structured snapshot data (+ cpu source)
gps_camera_logs.txt            ← GPS / camera events
network_calls.txt              ← network / API / SDK events
app_logs.txt                   ← full logcat
battery_stats.txt              ← batterystats dump
session_config.json            ← the resolved SessionConfig for this run
raw_data.json                  ← all collected data
```

---

### File structure

```
perf_framework/
├── framework.py          ← orchestrator; run_session() + CLI
├── run_parallel.py       ← multi-device fan-out launcher
├── config.py             ← constants, benchmarks, SessionConfig (layered)
├── core/
│   └── adb.py            ← serial-bound ADB command layer + device resolution
├── modules/
│   ├── sampling.py       ← shared CPU (cpuinfo) + meminfo parsers
│   ├── device.py         ← device profile & suitability
│   ├── start_time.py     ← cold / warm (true) / hot start
│   ├── capture.py        ← CPU+mem loop + in-process logcat filtering
│   ├── snapshots.py      ← auto + per-device-triggered snapshots
│   ├── battery.py        ← batterystats + simulated-unplug
│   └── network.py        ← SDK detection & redundancy analysis
├── analysis/
│   ├── llm_analyser.py   ← narrative + structured JSON (anthropic/gemini/openai)
│   └── benchmarks.py     ← Android Vitals thresholds
└── report/
    └── generator.py      ← Word report builder (10 sections)
```

---

### Notes / known limitations

- The framework does **not** drive the UI. Pair it with your automation, which
  runs independently against the same device(s).
- GPS/camera counts from `batterystats` are **indicative** — the `+gps`/`+camera`
  history markers are OEM/version-dependent. Treat them as signals, not ground truth.
- CPU% is reported device-wide (0–100 across the SoC), which is what the benchmarks
  in `config.py` assume.
