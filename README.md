# Android Mobile Performance Testing Framework — v4.2

A lightweight, serial-bound performance harness for Android apps. It **observes**
an app while *you* (or your automation) drive it, then produces a formatted Word
report covering start times, memory, CPU, GPS/camera, background jobs and
network/SDK activity, with optional LLM analysis.

> **Key mental model:** this framework does **not** tap through your app. It
> launches the activity and records what happens. You must drive the UI —
> manually, or via Appium / Maestro / monkey — during the capture window.
> If nothing drives the app, most tables will be near-empty (see Troubleshooting).

---

## 1. Requirements

| Need | Detail |
|------|--------|
| Python | 3.9+ (`python3`) |
| adb | On `PATH`, device authorised (`adb devices` shows `device`) |
| python-docx | Auto-installed on first run; or `pip3 install python-docx` |
| Device/emulator | API 26+ recommended. A **real device** is required for meaningful battery/GPS/camera data — emulators barely populate hardware rails. |
| LLM key (optional) | For Section 7/8 AI analysis. Without it the report falls back to rule-based recommendations. |

---

## 2. Quick start

### Interactive (single device — prompts you)
```bash
python3 framework.py
```
Runs until **you press Enter**. Drive the app during that window. This is why a
run can be "2 minutes" — it lasts exactly as long as you leave it open before
pressing Enter. There is no fixed timer in this mode.

### Unattended / fixed duration  ← run for exactly N minutes
```bash
python3 framework.py \
  --package com.dpworld.drivex.tankers.nonprod \
  --serial emulator-5554 \
  --duration 30
```
`--duration 30` captures for exactly 30 minutes, then finalises. Passing
`--duration` automatically switches off interactive prompts, so `--package` is
required (there's no operator to type it).

### Parallel across every connected device
```bash
python3 run_parallel.py --package com.example.app --duration 30
```

---

## 3. The four timing knobs (and where to set them)

These are the only things that control *when* and *how long* it captures.

| Knob | Controls | Default | Set via CLI | Set in code |
|------|----------|---------|-------------|-------------|
| **Test duration** | How long the capture window runs (unattended only) | none (interactive waits for Enter) | `--duration <min>` | `SessionConfig.duration_min` |
| **Snapshot mode** | Which snapshot triggers are active | `3` (both) | `--snap-mode {1,2,3}` | `SessionConfig.snap_mode` |
| **Auto interval** | Minutes between automatic snapshots | `5` | `--auto-interval <min>` | `SessionConfig.auto_interval_min` |
| **Perf loop interval** | Seconds between continuous CPU+memory samples | `10` | *(no CLI flag)* | `config.py → PERF_LOOP_INTERVAL_SEC`, or `"perf_interval_sec"` in a JSON config |

**Snapshot mode values:**
- `1` = **auto only** — snapshots on the timer (`--auto-interval`)
- `2` = **manual only** — snapshots only when you trigger them (timer disabled)
- `3` = **both** — timer + manual

> Note: at short durations you get **no auto-snapshots**. With the default 5-min
> interval, a run shorter than 5 minutes produces only `baseline-idle` and
> `session-end`. For a real trend, run ≥15 min or lower `--auto-interval`.

---

## 4. What snapshots get taken

A "snapshot" is a labelled, point-in-time capture: full `dumpsys meminfo` +
CPU sample → parsed into total PSS, native/dalvik/java heap, graphics, GL mtrack,
swap, and CPU%. Written to `snapshot_<label>.txt` and appended to
`snapshots_summary.json`.

Every run **always** takes two, regardless of mode:
- `baseline-idle` — just after launch (Step 7)
- `session-end` — at the end of the window (Step 11)

Plus, depending on mode:
- **Auto** — `auto_<n>_at_<HHMMSS>` every `--auto-interval` minutes
- **Manual** — fire one any time from another terminal:
  ```bash
  echo "after-login" > /tmp/perf_snapshot_trigger_<serial>
  ```
  (The exact path is printed when the run starts; the serial is appended so
  parallel runs don't collide.)

Separately, a **continuous CPU+memory loop** writes to `perf_stats.txt` every
`perf_interval_sec` (10s) for the whole run — that's not a snapshot, just a
background time series.

---

## 5. Battery — what you actually get

This is the most misunderstood part, so read this before reading Section 5/9 of
any report.

**While a device is on USB it is charging**, so *absolute mAh drain*
(`charge_start − charge_end`) cannot be measured directly. To work around this,
the framework runs `dumpsys battery unplug` at the start (`simulate_unplug`,
on by default). That makes batterystats **accrue on-battery accounting**
(screen/CPU/GPS/camera events) even while tethered, and sets `was_charging=False`.

So on a normal run you **do** get: GPS activations, camera sessions, temperature,
WorkManager/Firebase job counts. You do **not** get true physical mAh drain —
for that, use wireless adb (see below).

**Report behaviour (v4.2, patched):**
- The "Battery Testing — Approach & Methodology" section now only appears when
  drain data is genuinely **unavailable** (device counted as charging, or the
  unplug simulation failed). On a normal simulated-unplug run it is **omitted**
  and the Performance Scorecard becomes Section 9. This removes the old
  always-on battery lecture.
- Toggle: the gate lives in `report/generator.py` — search for
  `drain_unavailable`. Force it on with `drain_unavailable = True`.

**Flags:**
- `--no-unplug` — skip the unplug simulation (then drain is unavailable and the
  methodology section returns)
- `--bugreport` — also capture `bugreport.zip` for Battery Historian

**For true mAh drain — wireless adb:**
```bash
adb tcpip 5555
adb connect <device-ip>:5555
# unplug USB, then run the framework over wifi with --duration
```

---

## 6. LLM analysis (optional)

Your last report showed *"LLM analysis not available — check API key"* — that's
just a missing key, not a bug. Set one and Sections 7 & 8 fill in:

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # default provider
# or choose another provider:
export PERF_LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
```
Providers and model strings live in `config.py` (`LLM_PROVIDER`, `LLM_MODELS`).
Skip LLM entirely with `--no-llm`. Without a key, recommendations are still
generated rule-based.

---

## 7. All CLI flags

| Flag | Meaning |
|------|---------|
| `--package <name>` | App package (required unattended) |
| `--serial <id>` | Target device (auto if only one connected) |
| `--activity <name>` | Main activity (auto-detected if omitted) |
| `--duration <min>` | Unattended capture length; implies non-interactive |
| `--noninteractive` | No prompts (needs `--package` + `--duration`) |
| `--snap-mode {1,2,3}` | auto / manual / both |
| `--auto-interval <min>` | Minutes between auto snapshots |
| `--no-llm` | Skip LLM analysis |
| `--no-unplug` | Skip simulated battery unplug |
| `--bugreport` | Capture bugreport.zip |
| `--llm-provider {anthropic,gemini,openai}` | Override provider |
| `--config <file.json>` | Load a JSON session config |
| `--output-root <dir>` | Override output location |

**Config precedence (low → high):** defaults → JSON `--config` → environment →
CLI flags. So a CLI flag always wins.

### Example JSON config
```json
{
  "package": "com.dpworld.drivex.tankers.nonprod",
  "serial": "emulator-5554",
  "duration_min": 30,
  "snap_mode": 3,
  "auto_interval_min": 5,
  "perf_interval_sec": 10,
  "simulate_unplug": true,
  "use_llm": true
}
```
```bash
python3 framework.py --config runs/nonprod.json
```

---

## 8. Output files

Written to `~/Desktop/PerfFramework_Output/<app>_<serial>_<timestamp>/`:

| File | Contents |
|------|----------|
| `PerfReport_<app>_<date>.docx` | The formatted report |
| `snapshot_<label>.txt` | Each snapshot's raw meminfo + CPU |
| `snapshots_summary.json` | Parsed metrics for every snapshot |
| `perf_stats.txt` | Continuous CPU+memory time series |
| `gps_camera_logs.txt` / `network_calls.txt` / `app_logs.txt` | Filtered logcat streams |
| `battery_stats.txt` | Raw `dumpsys batterystats` |
| `session_config.json` | Exact config used for the run |
| `raw_data.json` | Everything fed to the report/LLM |

---

## 9. Troubleshooting

| Symptom | Cause & fix |
|---------|-------------|
| **"It only ran 2 minutes"** | Interactive mode ran until Enter was pressed. Use `--duration 30` for a fixed window, or just leave it open longer. |
| **Battery/GPS/camera tables all zero** | (a) Nothing drove the app — the framework only observes, you must interact; (b) it's an **emulator** (fake battery, empty hardware rails) — use a real device; (c) run was too short for events to accrue. |
| **No `auto_*` snapshots** | Run was shorter than `--auto-interval` (default 5 min). Lengthen the run or lower the interval. |
| **CPU max freq shows `0.0 GHz`** | Emulator/kernel restricts `cpufreq` sysfs. Cosmetic; expected on emulators. |
| **Idle CPU flagged POOR (~18%)** | Baseline snapshot caught app startup churn. Take baseline after the app settles, or judge idle from a later low-activity snapshot. |
| **"LLM analysis not available"** | No API key. `export ANTHROPIC_API_KEY=...` or run `--no-llm`. |
| **Battery methodology page appearing when not needed** | Fixed in v4.2 — it's now gated on `drain_unavailable` in `report/generator.py`. |
| **"more than one device"** | Pass `--serial <id>`, or use `run_parallel.py`. |

---

## 10. Project layout

```
android-perf_framework/
├── framework.py            # Orchestrator + CLI + interactive flow
├── run_parallel.py         # Fan out across all connected devices
├── config.py               # Defaults, benchmarks, SessionConfig  ← edit knobs here
├── core/
│   └── adb.py              # Serial-bound adb command layer
├── modules/
│   ├── device.py           # Device profile + suitability score
│   ├── start_time.py       # Cold / warm start measurement
│   ├── sampling.py         # CPU + meminfo parsing (single source of truth)
│   ├── capture.py          # Continuous CPU/mem loop + logcat streams
│   ├── snapshots.py        # Auto + manual snapshot engine
│   ├── battery.py          # batterystats capture + simulated unplug
│   └── network.py          # SDK detection + redundant-call analysis
├── analysis/
│   ├── llm_analyser.py     # Anthropic / Gemini / OpenAI integration
│   └── benchmarks.py       # Threshold helpers
└── report/
    └── generator.py        # Word report builder  ← battery-section gate here
```

### "How do I…" quick reference
| I want to… | Edit |
|------------|------|
| Change default capture cadence | `config.py → PERF_LOOP_INTERVAL_SEC` |
| Change default auto-snapshot interval | `config.py → SessionConfig.auto_interval_min` |
| Change benchmark thresholds | `config.py → BENCHMARKS` |
| Change LLM provider/model | `config.py → LLM_PROVIDER`, `LLM_MODELS` |
| Always/never show battery methodology | `report/generator.py → drain_unavailable` |
| Change report colours/branding | `report/generator.py` top constants |