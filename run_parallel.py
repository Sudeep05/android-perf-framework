#!/usr/bin/env python3
"""
run_parallel.py — Fan out an unattended session across every connected device.

Replaces the manual "5 terminals, 5 copies" methodology with one command. Each
device gets its own ADB(serial), output directory, and per-serial trigger file,
so there is zero cross-talk.

    python3 run_parallel.py --package com.example.app --duration 30
    python3 run_parallel.py --config runs/driverx.json --serials RZ8N,RF9X

Parallel runs are always non-interactive (there is no single operator to prompt),
so --duration is required.
"""

import sys
import os
import argparse
import dataclasses
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))

from core.adb import list_devices
from config import SessionConfig
from framework import run_session, parse_args as _fw_parse, C


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Parallel multi-device perf runner")
    p.add_argument("--package", help="App package (or via --config)")
    p.add_argument("--activity")
    p.add_argument("--config")
    p.add_argument("--duration", dest="duration_min", type=int, required=False)
    p.add_argument("--serials", help="Comma-separated subset; default = all connected")
    p.add_argument("--snap-mode", dest="snap_mode", type=int, choices=[1, 2, 3], default=1)
    p.add_argument("--auto-interval", dest="auto_interval_min", type=int, default=5)
    p.add_argument("--no-llm", dest="use_llm", action="store_false", default=None)
    p.add_argument("--no-unplug", dest="simulate_unplug", action="store_false", default=None)
    p.add_argument("--llm-provider", dest="llm_provider",
                   choices=["anthropic", "gemini", "openai"])
    p.add_argument("--output-root", dest="output_root")
    return vars(p.parse_args(argv))


def _cfg_for(serial, base_cli):
    cli = dict(base_cli)
    cli.pop("serials", None)
    cli["serial"] = serial
    cli["noninteractive"] = True
    cfg = SessionConfig.from_layers(cli)
    cfg.validate_for_unattended()
    return cfg


def main(argv=None):
    cli = parse_args(argv)
    requested = cli.pop("serials", None)
    serials = ([s.strip() for s in requested.split(",") if s.strip()]
               if requested else list_devices())

    if not serials:
        print(f"{C.RED}No devices connected.{C.END}"); sys.exit(1)

    print(f"{C.BOLD}{C.BLUE}Fanning out across {len(serials)} device(s): "
          f"{', '.join(serials)}{C.END}")

    try:
        cfgs = [_cfg_for(s, cli) for s in serials]
    except ValueError as e:
        print(f"{C.RED}{e}{C.END}"); sys.exit(2)

    results = {}
    with ThreadPoolExecutor(max_workers=len(cfgs)) as ex:
        futures = {ex.submit(run_session, cfg, show_banner=False): cfg.serial
                   for cfg in cfgs}
        for fut in as_completed(futures):
            serial = futures[fut]
            try:
                results[serial] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[serial] = f"ERROR: {e}"

    print(f"\n{C.BOLD}── Parallel run summary ──{C.END}")
    for serial, res in results.items():
        status = f"{C.GREEN}{res}{C.END}" if res and "ERROR" not in str(res) \
                 else f"{C.RED}{res}{C.END}"
        print(f"  {serial}: {status}")


if __name__ == "__main__":
    main()
