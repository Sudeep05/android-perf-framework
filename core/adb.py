"""
core/adb.py — Serial-bound ADB command layer.

Every adb interaction in the framework goes through an ADB instance. Binding a
serial at construction time means:

  * Multiple devices can be tested in parallel — each run owns one ADB(serial).
  * No module ever emits a bare `adb shell` that would fail with
    "more than one device" once a second handset is plugged in.
  * The command layer is mockable: tests swap ADB for a fake with the same API.

Design notes
------------
- `shell()` / `raw()` never raise on non-zero exit or timeout; they return "".
  Callers in this framework treat missing data as "not available", not fatal.
- `stream()` starts a background logcat (or any long-lived adb command) WITHOUT
  a shell pipe. Filtering happens in-process (see modules/capture.py), which
  removes the OS `grep` dependency and the shell-injection surface.
"""

from __future__ import annotations
import subprocess
import shlex
from typing import List, Optional


class ADB:
    def __init__(self, serial: Optional[str] = None, default_timeout: int = 15):
        self.serial = serial
        self.default_timeout = default_timeout
        self._base: List[str] = ["adb"] + (["-s", serial] if serial else [])

    # ── identity ─────────────────────────────────────────────────────────
    @property
    def tag(self) -> str:
        """Short, filesystem-safe id for this device (for filenames/paths)."""
        return (self.serial or "default").replace(":", "_").replace(".", "_")

    # ── device-side shell ────────────────────────────────────────────────
    def shell(self, cmd: str, timeout: Optional[int] = None) -> str:
        """Run `adb [-s serial] shell <cmd>`; return stdout stripped, "" on error."""
        return self._run(self._base + ["shell", cmd], timeout)

    # ── host-side adb (devices, get-serialno, bugreport, install ...) ─────
    def raw(self, args: List[str], timeout: Optional[int] = None) -> str:
        """Run `adb [-s serial] <args...>`; return stdout stripped, "" on error."""
        return self._run(self._base + args, timeout)

    def raw_cp(self, args: List[str], timeout: Optional[int] = None):
        """Like raw() but return the CompletedProcess (for callers needing rc/stderr)."""
        try:
            return subprocess.run(self._base + args, capture_output=True,
                                  text=True, timeout=timeout or self.default_timeout)
        except Exception as e:  # noqa: BLE001
            class _Fake:
                returncode = 1
                stdout = ""
                stderr = str(e)
            return _Fake()

    # ── long-lived stream (logcat) — no shell, returns Popen ─────────────
    def stream(self, args: List[str]) -> "subprocess.Popen[str]":
        """Start a long-lived adb command, stdout as a text pipe for a reader thread."""
        return subprocess.Popen(
            self._base + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,  # line-buffered
        )

    # ── health ───────────────────────────────────────────────────────────
    def is_online(self) -> bool:
        out = self.raw(["get-state"])
        return out.strip() == "device"

    # ── internal ─────────────────────────────────────────────────────────
    def _run(self, argv: List[str], timeout: Optional[int]) -> str:
        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               timeout=timeout or self.default_timeout)
            return r.stdout.strip()
        except Exception:  # noqa: BLE001 — timeout, adb missing, device gone
            return ""

    def __repr__(self) -> str:
        return f"ADB(serial={self.serial or 'default'})"


# ─────────────────────────────────────────────────────────────────────────────
# Host-level helpers (not bound to a serial)
# ─────────────────────────────────────────────────────────────────────────────
def list_devices() -> List[str]:
    """Return serials of all authorised, online devices."""
    try:
        r = subprocess.run(["adb", "devices"], capture_output=True,
                           text=True, timeout=10)
    except Exception:
        return []
    serials = []
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def resolve_serial(requested: Optional[str]) -> Optional[str]:
    """
    Decide which serial a run should target.

    - explicit serial requested  -> validate it is connected, else raise
    - exactly one device         -> use it (serial-bound anyway, for safety)
    - multiple, none requested    -> raise (ambiguous; caller must pick or fan out)
    - none connected              -> raise
    """
    devices = list_devices()
    if requested:
        if requested not in devices:
            raise RuntimeError(
                f"Requested serial '{requested}' not connected. "
                f"Online devices: {devices or 'none'}")
        return requested
    if len(devices) == 1:
        return devices[0]
    if len(devices) == 0:
        raise RuntimeError("No authorised devices connected.")
    raise RuntimeError(
        f"{len(devices)} devices connected {devices}; pass --serial <id>, "
        f"or use run_parallel.py to fan out across all of them.")
