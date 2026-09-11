"""A short-lived obs-websocket connection per tool call, with auto-launch.

OBS is not always running when the agent needs it -- it should not have to be.
``ensure_connected`` launches OBS from a cold start if necessary and blocks
until the websocket actually accepts requests, since the process existing and
the websocket server being ready are two different moments.
"""

from __future__ import annotations

import time

import obsws_python as obsws

from . import paths


class ObsUnavailable(RuntimeError):
    pass


def _try_connect(settings: dict, timeout: float = 3.0) -> obsws.ReqClient:
    return obsws.ReqClient(
        host=settings["host"], port=settings["port"],
        password=settings["password"], timeout=timeout,
    )


def connect() -> obsws.ReqClient:
    """Connect to an already-running OBS. Raises with a clear reason if not."""
    settings = paths.websocket_settings()
    if not settings["enabled"]:
        paths.enable_websocket_server()
        raise ObsUnavailable(
            "obs-websocket was disabled; it is now enabled in config but OBS "
            "must be restarted (or launched) to pick that up. Call obs_ensure_running."
        )
    try:
        return _try_connect(settings)
    except Exception as exc:  # obsws raises its own ConnectionError subclasses
        if not paths.running_pids():
            raise ObsUnavailable("OBS is not running. Call obs_ensure_running first.") from exc
        raise ObsUnavailable(f"OBS is running but the websocket did not respond: {exc}") from exc


def ensure_running(wait_s: float = 25.0) -> dict:
    """Launch OBS if needed and block until the websocket answers a request."""
    settings = paths.websocket_settings()
    if not settings["enabled"]:
        settings = paths.enable_websocket_server() | {
            "host": settings["host"], "port": settings["port"], "password": settings["password"],
        }

    pids = paths.running_pids()
    launched_pid = None
    if not pids:
        launched_pid = paths.launch()

    deadline = time.monotonic() + wait_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client = _try_connect(settings, timeout=2.0)
            version = client.get_version()
            client.disconnect()
            return {
                "launched": launched_pid is not None,
                "launched_pid": launched_pid,
                "obs_version": version.obs_version,
                "websocket_version": version.obs_web_socket_version,
                "seconds_to_connect": round(wait_s - (deadline - time.monotonic()), 1),
            }
        except Exception as exc:  # noqa: BLE001 -- retry loop, any failure just means "not yet"
            last_error = exc
            time.sleep(0.5)

    raise ObsUnavailable(
        f"OBS did not accept websocket connections within {wait_s}s. "
        f"Last error: {last_error}"
    )
