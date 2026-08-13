"""
config.py — Central configuration + session model.

Two things live here:
  1. Static tuning constants and benchmark thresholds (unchanged from v4.1).
  2. SessionConfig — the single object describing ONE run. It is built by
     layering (lowest precedence first):
         defaults  <  JSON config file  <  environment  <  CLI flags
     so the same framework runs interactively on a desk or fully unattended
     in CI from a --config file, with no code changes.
"""

from __future__ import annotations
import os
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# LLM Provider Configuration
# ─────────────────────────────────────────────────────────────────────────────
LLM_PROVIDER = os.environ.get("PERF_LLM_PROVIDER", "anthropic")

LLM_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "gemini":    "gemini-1.5-flash",
    "openai":    "gpt-4o",
}

API_KEYS = {
    "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
    "gemini":    os.environ.get("GEMINI_API_KEY", ""),
    "openai":    os.environ.get("OPENAI_API_KEY", ""),
}

# ─────────────────────────────────────────────────────────────────────────────
# Framework defaults
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_COLD_WARM_RUNS   = 3
PERF_LOOP_INTERVAL_SEC   = 10
OUTPUT_DIR               = os.path.join(os.path.expanduser("~"), "Desktop", "PerfFramework_Output")

# Trigger files are now PER-DEVICE (see SessionConfig.trigger_file). This is the
# base directory only; the serial is appended so parallel runs never collide.
TRIGGER_DIR              = "/tmp"
TRIGGER_PREFIX           = "perf_snapshot_trigger"

# ─────────────────────────────────────────────────────────────────────────────
# Industry benchmark thresholds (Google / Android standards)
# ─────────────────────────────────────────────────────────────────────────────
BENCHMARKS = {
    "cold_start_ms":     {"excellent": 1000, "good": 2000, "acceptable": 5000},
    "warm_start_ms":     {"excellent": 200,  "good": 800,  "acceptable": 2000},
    "idle_pss_mb":       {"excellent": 50,   "good": 100,  "acceptable": 150},
    "active_pss_mb":     {"excellent": 100,  "good": 200,  "acceptable": 300},
    "idle_cpu_pct":      {"excellent": 2,    "good": 5,    "acceptable": 10},
    "active_cpu_pct":    {"excellent": 30,   "good": 50,   "acceptable": 80},
    "gl_mtrack_mb":      {"excellent": 10,   "good": 20,   "acceptable": 40},
    "swap_pss_mb":       {"excellent": 0,    "good": 10,   "acceptable": 30},
    "gps_activations_per_min": {"excellent": 2, "good": 6, "acceptable": 12},
    "camera_sessions_per_trip": {"excellent": 4, "good": 8, "acceptable": 14},
}

RAM_TIERS = {
    "low":    (0,   3),
    "medium": (3,   6),
    "high":   (6,   10),
    "ultra":  (10,  999),
}

MIN_RECOMMENDED = {
    "ram_gb":         4,
    "android_api":    26,
    "cpu_cores":      4,
    "cpu_freq_ghz":   1.8,
}


# ─────────────────────────────────────────────────────────────────────────────
# Session model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SessionConfig:
    """Everything needed to run one device session. Serializable to/from JSON."""
    # target
    serial:        Optional[str] = None
    package:       Optional[str] = None
    activity:      Optional[str] = None          # None -> auto-detect

    # session shape
    interactive:   bool = True                   # False = fully unattended
    duration_min:  Optional[int] = None          # unattended stop after N min
    snap_mode:     int = 3                        # 1 auto | 2 manual | 3 both
    auto_interval_min: Optional[int] = 5
    cold_warm_runs: int = DEFAULT_COLD_WARM_RUNS
    perf_interval_sec: int = PERF_LOOP_INTERVAL_SEC

    # battery
    simulate_unplug: bool = True                 # dumpsys battery unplug trick
    capture_bugreport: bool = False

    # analysis / output
    use_llm:       bool = True
    llm_provider:  str = LLM_PROVIDER
    output_root:   str = OUTPUT_DIR

    # populated at runtime
    session_dir:   Optional[str] = field(default=None, compare=False)
    started_epoch: Optional[float] = field(default=None, compare=False)

    # ── derived ──────────────────────────────────────────────────────────
    @property
    def trigger_file(self) -> str:
        tag = (self.serial or "default").replace(":", "_").replace(".", "_")
        return os.path.join(TRIGGER_DIR, f"{TRIGGER_PREFIX}_{tag}")

    # ── construction ─────────────────────────────────────────────────────
    @classmethod
    def from_layers(cls, cli: dict) -> "SessionConfig":
        """
        Merge precedence (low -> high): defaults < JSON file < env < CLI.
        `cli` is the dict of argparse values (None means 'not provided').
        """
        data: dict = {}

        # 1. JSON config file
        cfg_path = cli.get("config") or os.environ.get("PERF_CONFIG")
        if cfg_path and os.path.exists(cfg_path):
            with open(cfg_path) as f:
                data.update(json.load(f))

        # 2. environment overrides
        env_map = {
            "serial":       os.environ.get("ANDROID_SERIAL"),
            "package":      os.environ.get("PERF_PACKAGE"),
            "activity":     os.environ.get("PERF_ACTIVITY"),
            "llm_provider": os.environ.get("PERF_LLM_PROVIDER"),
        }
        data.update({k: v for k, v in env_map.items() if v})

        # 3. CLI overrides (only keys the user actually passed)
        data.update({k: v for k, v in cli.items()
                     if v is not None and k != "config"})

        # Non-interactive is implied by --duration or explicit --noninteractive
        if data.get("noninteractive") or data.get("duration_min"):
            data["interactive"] = False
        data.pop("noninteractive", None)

        # Keep only recognised fields
        allowed = set(cls.__dataclass_fields__.keys())
        clean = {k: v for k, v in data.items() if k in allowed}
        return cls(**clean)

    def to_json(self) -> str:
        return json.dumps({k: v for k, v in asdict(self).items()
                           if k not in ("session_dir", "started_epoch")}, indent=2)

    def validate_for_unattended(self) -> None:
        if not self.interactive:
            missing = [k for k in ("package",) if not getattr(self, k)]
            if missing:
                raise ValueError(
                    f"Unattended run requires: {', '.join(missing)} "
                    f"(set via --package, env PERF_PACKAGE, or --config).")
            if not self.duration_min:
                raise ValueError(
                    "Unattended run requires --duration <minutes> so it knows "
                    "when to stop (there is no operator to press Enter).")
