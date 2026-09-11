"""Locate the OBS install and its obs-websocket connection settings.

Mirrors the defensive approach used for CapCut: the registry's recorded
install location goes stale when an app is reinstalled onto a different
drive, and stat()'ing a broken junction raises OSError rather than returning
False. Every probe here treats that as "not found", not as a crash.
"""

from __future__ import annotations

import json
import os
import subprocess
import winreg
from pathlib import Path

EXE_REL = Path("bin") / "64bit" / "obs64.exe"
ENV_OBS_EXE = "OBS_MCP_EXE"
WS_CONFIG = (
    Path(os.environ.get("APPDATA", ""))
    / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
)


def _is_file(p: Path) -> bool:
    try:
        return p.is_file()
    except OSError:
        return False


def _registry_hint() -> Path | None:
    for hive, sub in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ):
        try:
            with winreg.OpenKey(hive, sub) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as entry:
                            name, _ = winreg.QueryValueEx(entry, "DisplayName")
                            if str(name) == "OBS Studio":
                                icon, _ = winreg.QueryValueEx(entry, "DisplayIcon")
                                return Path(str(icon))
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def find_exe() -> Path:
    """Return obs64.exe, raising if it cannot be located anywhere plausible."""
    env = os.environ.get(ENV_OBS_EXE)
    if env and _is_file(Path(env)):
        return Path(env)

    hint = _registry_hint()
    if hint and _is_file(hint):
        return hint

    # The registry's DisplayIcon path is what goes stale after a drive
    # reorganisation; re-derive the same relative layout on every drive root.
    import string
    for letter in string.ascii_uppercase:
        for base in (f"{letter}:/OBS/obs-studio", f"{letter}:/Program Files/obs-studio"):
            cand = Path(base) / EXE_REL
            if _is_file(cand):
                return cand

    raise FileNotFoundError(
        f"obs64.exe not found. Set {ENV_OBS_EXE} to its full path."
    )


def websocket_settings() -> dict:
    """Read host/port/password/enabled from OBS's own websocket config."""
    if not _is_file(WS_CONFIG):
        raise FileNotFoundError(
            f"No obs-websocket config at {WS_CONFIG}. Start OBS at least once first."
        )
    cfg = json.loads(WS_CONFIG.read_text(encoding="utf-8"))
    return {
        "host": "127.0.0.1",
        "port": cfg.get("server_port", 4455),
        "password": cfg.get("server_password", ""),
        "enabled": bool(cfg.get("server_enabled", False)),
        "auth_required": bool(cfg.get("auth_required", True)),
    }


def enable_websocket_server() -> dict:
    """Flip server_enabled on in the config, for a restart to pick up."""
    cfg = json.loads(WS_CONFIG.read_text(encoding="utf-8"))
    cfg["server_enabled"] = True
    WS_CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def running_pids() -> list[int]:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        parts = [c.strip('" ') for c in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "obs64.exe":
            try:
                pids.append(int(parts[1]))
            except ValueError:
                continue
    return pids


def launch(exe: Path | None = None) -> int:
    """Start OBS minimised to the tray, in its own directory.

    OBS resolves its Data/ folder relative to the process working directory,
    so launching with any other cwd silently breaks plugin loading.
    """
    target = exe or find_exe()
    proc = subprocess.Popen(
        [str(target), "--minimize-to-tray", "--disable-shutdown-check"],
        cwd=str(target.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid
