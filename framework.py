#!/usr/bin/env python3
"""
framework.py — Android Mobile Performance Testing Framework v4.2

Two ways to run:

  Interactive (single device, prompts as before):
      python3 framework.py

  Unattended (headless / CI / alongside an external UI-automation driver):
      python3 framework.py --package com.example.app --duration 30 --serial RZ8N...
      python3 framework.py --config runs/driverx.json

  Parallel across every connected device:
      python3 run_parallel.py --package com.example.app --duration 30

The framework OBSERVES; your automation (Appium/Maestro/monkey/manual) drives
the UI. In unattended mode it captures for --duration minutes, then finalises.
"""

import sys
import os
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from core.adb import ADB, resolve_serial
from config import SessionConfig, LLM_PROVIDER
import config as _config


# ── terminal styling ─────────────────────────────────────────────────────────
class C:
    BLUE="\033[94m"; GREEN="\033[92m"; YELLOW="\033[93m"; RED="\033[91m"
    BOLD="\033[1m"; END="\033[0m"; CYAN="\033[96m"

def banner():
    print(f"""
{C.BLUE}{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║     Android Mobile Performance Testing Framework  v4.2       ║
║     Performance Engineering CoE                               ║
╚══════════════════════════════════════════════════════════════╝{C.END}
""")

def step(n, text): print(f"\n{C.BOLD}{C.CYAN}── Step {n}: {text} ──{C.END}")
def ok(t):   print(f"  {C.GREEN}✔  {t}{C.END}")
def warn(t): print(f"  {C.YELLOW}⚠  {t}{C.END}")
def err(t):  print(f"  {C.RED}✖  {t}{C.END}")
def info(t): print(f"  {C.BLUE}ℹ  {t}{C.END}")


# ── interactive prompt helpers ────────────────────────────────────────────────
def _ask(prompt, choices=None, default=None):
    opts = " ".join(f"[{c}]" for c in choices) if choices else ""
    while True:
        ans = input(f"  {C.BOLD}{prompt} {opts}: {C.END}").strip()
        if not ans and default is not None:
            return default
        if choices and ans not in choices:
            print(f"  {C.YELLOW}Enter one of: {', '.join(choices)}{C.END}"); continue
        return ans

def _ask_int(prompt, choices, default=None):
    return int(_ask(prompt, [str(c) for c in choices],
                    str(default) if default is not None else None))


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Android Performance Testing Framework v4.2")
    p.add_argument("--serial", help="Target device serial (adb -s). Auto if one device.")
    p.add_argument("--package", help="App package name, e.g. com.example.app")
    p.add_argument("--activity", help="Main activity (auto-detected if omitted)")
    p.add_argument("--config", help="JSON session config file")
    p.add_argument("--duration", dest="duration_min", type=int,
                   help="Unattended capture length in minutes (implies non-interactive)")
    p.add_argument("--noninteractive", action="store_true",
                   help="Run without prompts (requires --package and --duration)")
    p.add_argument("--snap-mode", dest="snap_mode", type=int, choices=[1, 2, 3])
    p.add_argument("--auto-interval", dest="auto_interval_min", type=int)
    p.add_argument("--no-llm", dest="use_llm", action="store_false", default=None)
    p.add_argument("--no-unplug", dest="simulate_unplug", action="store_false", default=None)
    p.add_argument("--bugreport", dest="capture_bugreport", action="store_true", default=None)
    p.add_argument("--llm-provider", dest="llm_provider", choices=["anthropic", "gemini", "openai"])
    p.add_argument("--output-root", dest="output_root")
    return vars(p.parse_args(argv))


# ── main session (importable — run_parallel calls this per device) ────────────
def run_session(cfg: SessionConfig, show_banner=True):
    if show_banner:
        banner()

    # sync LLM provider override
    if cfg.llm_provider:
        _config.LLM_PROVIDER = cfg.llm_provider

    # ── 1. Resolve device + ADB ──────────────────────────────────────────
    step(1, "Device Connection")
    serial = resolve_serial(cfg.serial)
    cfg.serial = serial
    adb = ADB(serial)
    if not adb.is_online():
        err(f"Device {serial} not online."); return None
    ok(f"Device connected: {serial}")

    # ── 2. App + activity ────────────────────────────────────────────────
    from modules.device import (get_device_info, get_app_info, get_main_activity,
                                 assess_suitability, is_installed)
    step(2, "App Configuration")
    if cfg.interactive and not cfg.package:
        cfg.package = _ask("Enter app package name (e.g. com.example.app)")
    if not cfg.package:
        err("Package name is required."); return None
    if not is_installed(adb, cfg.package):
        err(f"Package '{cfg.package}' not found on {serial}."); return None
    ok(f"App found: {cfg.package}")

    auto_activity = get_main_activity(adb, cfg.package)
    if cfg.interactive and not cfg.activity:
        cfg.activity = _ask(f"Main activity (detected: {auto_activity}, Enter to accept)",
                            default=auto_activity)
    cfg.activity = cfg.activity or auto_activity
    ok(f"Activity: {cfg.activity}")

    app_info = get_app_info(adb, cfg.package)
    ok(f"Version: {app_info.get('version','N/A')}")

    # ── 3. Session configuration ─────────────────────────────────────────
    step(3, "Session Configuration")
    if cfg.interactive:
        print(f"\n  {C.BOLD}Snapshot mode:{C.END}  [1] auto  [2] manual  [3] both")
        cfg.snap_mode = _ask_int("Choose", [1, 2, 3], default=cfg.snap_mode)
        if cfg.snap_mode in (1, 3):
            cfg.auto_interval_min = _ask_int("Auto-snapshot interval (min)",
                                             [3, 5, 10, 15], default=cfg.auto_interval_min or 5)
        if cfg.snap_mode in (2, 3):
            print(f"  Manual snapshot: {C.CYAN}echo \"label\" > {cfg.trigger_file}{C.END}")
        cfg.use_llm = _ask("Run LLM analysis after test?", ["yes", "no"],
                           default="yes" if cfg.use_llm else "no") == "yes"
    if cfg.snap_mode == 2:
        cfg.auto_interval_min = None

    os.makedirs(cfg.output_root, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    cfg.session_dir = os.path.join(
        cfg.output_root, f"{cfg.package.split('.')[-1]}_{adb.tag}_{stamp}")
    os.makedirs(cfg.session_dir, exist_ok=True)
    cfg.started_epoch = time.time()          # <-- correct session-duration anchor
    ok(f"Output: {cfg.session_dir}")
    with open(os.path.join(cfg.session_dir, "session_config.json"), "w") as f:
        f.write(cfg.to_json())

    # ── 4. Device profile ────────────────────────────────────────────────
    step(4, "Device Profile")
    device_info = get_device_info(adb)
    suitability = assess_suitability(device_info)
    cores = device_info.get("cpu_cores", 0)
    ok(f"{device_info.get('brand','')} {device_info.get('model','')} | "
       f"{device_info.get('ram_total_gb','')} GB | {cores} cores @ "
       f"{device_info.get('cpu_max_freq_ghz','')} GHz | API {device_info.get('api_level','')}")
    ok(f"Suitability: {suitability['score']}/100 — {suitability['tier']}")
    for iss in suitability.get("issues", []):
        warn(iss)

    battery_data = {}
    llm_text, llm_structured = "", {}
    from modules.battery import (reset_batterystats, set_simulated_unplug,
                                 reset_battery_state, capture_battery_stats,
                                 capture_bugreport, parse_battery_stats)
    from modules.capture import CaptureEngine
    from modules.snapshots import SnapshotEngine

    cap_engine = snap_engine = None
    unplugged = False
    try:
        # ── 5. Reset + simulate unplug ───────────────────────────────────
        step(5, "Reset Battery Stats")
        reset_batterystats(adb)
        ok("Battery stats reset.")
        if cfg.simulate_unplug:
            unplugged = set_simulated_unplug(adb)
            ok("Simulated on-battery state (drain accounting enabled over USB).") if unplugged \
                else warn("Could not confirm simulated unplug; drain figures may be voided.")

        # ── 6. Cold + warm start ─────────────────────────────────────────
        step(6, "Cold & Warm Start")
        from modules.start_time import (measure_cold_start, measure_warm_start,
                                        summarise, rate_start_time)
        cold_summary = summarise(measure_cold_start(adb, cfg.package, cfg.activity, cfg.cold_warm_runs))
        ok(f"Cold avg: {cold_summary['avg']} ms  [{rate_start_time(cold_summary['avg'],'cold')}]")
        warm_summary = summarise(measure_warm_start(adb, cfg.package, cfg.activity, cfg.cold_warm_runs))
        ok(f"Warm avg: {warm_summary['avg']} ms  [{rate_start_time(warm_summary['avg'],'warm')}]")

        # ── 7. Baseline snapshot ─────────────────────────────────────────
        step(7, "Baseline Snapshot")
        adb.shell(f"am start -n {cfg.package}/{cfg.activity}")
        time.sleep(5)
        snap_engine = SnapshotEngine(adb, cfg.package, cfg.session_dir,
                                     cfg.trigger_file, cores=cores)
        snap_engine.take_snapshot("baseline-idle")
        ok("Baseline captured.")

        # ── 8-9. Start captures + snapshot engine ────────────────────────
        step(8, "Starting Background Captures")
        cap_engine = CaptureEngine(adb, cfg.package, cfg.session_dir, cfg.perf_interval_sec)
        cap_engine.start()
        ok(f"CPU+Memory loop every {cfg.perf_interval_sec}s; logcat streams live.")
        step(9, "Starting Snapshot Engine")
        snap_engine.start(auto_interval_min=cfg.auto_interval_min)
        ok("Snapshot engine ready.")

        # ── 10. Test session (wait) ──────────────────────────────────────
        _run_test_window(cfg)

        # ── 11. Final snapshot + stop ────────────────────────────────────
        step(11, "Final Snapshot")
        snap_engine.take_snapshot("session-end")
        time.sleep(2)
        snap_engine.stop()
        cap_engine.stop()
        snap_engine.save_summary()
        ok(f"Snapshots saved ({len(snap_engine.snapshots)} total)")

        # ── 12. Battery capture ──────────────────────────────────────────
        step(12, "Battery & Hardware Capture")
        stats_path = capture_battery_stats(adb, cfg.session_dir)
        battery_data = parse_battery_stats(stats_path, simulated_unplug=unplugged)
        ok(f"Camera sessions: {battery_data.get('camera_sessions',0)} | "
           f"GPS activations: {battery_data.get('gps_activations',0)}")
        if battery_data.get("was_charging"):
            warn("Device charging and unplug not simulated — drain figures unavailable.")
        do_bug = cfg.capture_bugreport
        if cfg.interactive:
            do_bug = _ask("Capture bugreport.zip? (2-3 min)", ["yes", "no"],
                          default="yes" if do_bug else "no") == "yes"
        if do_bug:
            capture_bugreport(adb, cfg.session_dir)

    finally:
        # Restore real charging state no matter what happened.
        if unplugged:
            reset_battery_state(adb)
            info("Restored real battery/charging state.")
        if cap_engine:
            cap_engine.stop()
        if snap_engine:
            snap_engine.stop()

    # ── 13. Network analysis ─────────────────────────────────────────────
    step(13, "Network & SDK Analysis")
    from modules.network import analyse_network_logs
    files = cap_engine.output_files()
    network_data = analyse_network_logs(files.get("network_calls"),
                                        files.get("app_logs"), cfg.package)
    ok(f"SDKs: {', '.join(network_data.get('sdks_detected', []) or ['None'])} | "
       f"redundant: {len(network_data.get('redundant_calls', []))} | "
       f"jobs: {network_data.get('total_jobs', 0)}")

    # ── 14. LLM analysis ─────────────────────────────────────────────────
    all_data_for_llm = {
        "device": device_info, "suitability": suitability,
        "cold_start": cold_summary, "warm_start": warm_summary,
        "snapshots": snap_engine.snapshots, "battery": battery_data,
        "network": network_data, "app_info": app_info,
    }
    if cfg.use_llm:
        step(14, f"LLM Analysis via {_config.LLM_PROVIDER.capitalize()}")
        from analysis.llm_analyser import analyse_with_llm, analyse_with_llm_structured
        info("Requesting narrative analysis...")
        llm_text = analyse_with_llm(all_data_for_llm)
        ok("Narrative analysis complete.")
        info("Requesting structured recommendations...")
        llm_structured = analyse_with_llm_structured(all_data_for_llm)
        rec_count = len(llm_structured.get("recommendations", []))
        if rec_count:
            ok(f"{rec_count} structured findings (risk: {llm_structured.get('overall_risk','?')})")
        else:
            warn("No structured LLM recs — falling back to rule-based.")

    # ── 15. Report ───────────────────────────────────────────────────────
    step(15, "Building Word Report")
    session_min = max(1, round((time.time() - cfg.started_epoch) / 60))
    all_data = {**all_data_for_llm, "session_duration_min": f"{session_min} minutes"}
    try:
        import docx  # noqa: F401
    except ImportError:
        import subprocess
        subprocess.run("pip3 install python-docx --break-system-packages -q", shell=True)
    from report.generator import build_report
    report_path = build_report(all_data, llm_text, cfg.session_dir,
                               llm_structured=llm_structured)
    ok(f"Report saved: {report_path}")

    # ── 16. Raw JSON ─────────────────────────────────────────────────────
    try:
        with open(os.path.join(cfg.session_dir, "raw_data.json"), "w") as f:
            json.dump({k: v for k, v in all_data.items() if k != "snapshots"},
                      f, indent=2, default=str)
    except Exception:
        pass

    print(f"\n{C.GREEN}{C.BOLD}  ✔ SESSION COMPLETE — {cfg.session_dir}{C.END}\n")
    return report_path


def _run_test_window(cfg: SessionConfig):
    """Block for the test: press-Enter (interactive) or sleep --duration (unattended)."""
    if cfg.interactive:
        print(f"""
{C.GREEN}{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║              ALL CAPTURES ARE NOW RUNNING                    ║
║  Drive the app (manually or via your automation).            ║
║  Manual snapshot:  echo "label" > {cfg.trigger_file}
║  Press Enter when the test session is complete.              ║
╚══════════════════════════════════════════════════════════════╝{C.END}""")
        input(f"  {C.BOLD}Press Enter when done...{C.END}")
    else:
        total = cfg.duration_min * 60
        info(f"Unattended capture for {cfg.duration_min} min "
             f"(snapshot: echo \"label\" > {cfg.trigger_file})")
        start = time.time()
        while time.time() - start < total:
            remaining = int(total - (time.time() - start))
            print(f"\r  {C.CYAN}Capturing… {remaining//60:02d}:{remaining%60:02d} left{C.END}",
                  end="", flush=True)
            time.sleep(1)
        print()


def main(argv=None):
    cli = parse_args(argv)
    cfg = SessionConfig.from_layers(cli)
    try:
        cfg.validate_for_unattended()
    except ValueError as e:
        err(str(e)); sys.exit(2)
    try:
        run_session(cfg)
    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}Interrupted. Partial data may be saved.{C.END}\n"); sys.exit(0)
    except Exception as e:  # noqa: BLE001
        print(f"\n{C.RED}Fatal error: {e}{C.END}")
        import traceback; traceback.print_exc(); sys.exit(1)


if __name__ == "__main__":
    main()
