"""MCP surface for OBS Studio, via obs-websocket.

Each tool opens a short connection, does one thing, and disconnects -- OBS
itself is the state, so there is nothing to keep alive between calls. The one
exception worth knowing: StopRecord's response returns the output path before
the file is fully flushed to disk, so obs_recording_stop polls
GetRecordStatus briefly until the output actually goes inactive before handing
the path back.
"""

from __future__ import annotations

import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import client as client_mod
from . import paths

mcp = MCPServer(
    "obs",
    instructions=(
        "Control local OBS Studio for autonomous screen recording. Call "
        "obs_probe first. If OBS is not running, call obs_ensure_running -- it "
        "launches OBS and waits for the websocket to come up. Recordings use "
        "whatever scene is currently active; check obs_scenes and obs_sources "
        "before recording if you need a specific capture source enabled."
    ),
)


def _client():
    return client_mod.connect()


# ----------------------------------------------------------------- lifecycle


@mcp.tool()
def obs_probe() -> dict:
    """Check OBS's install, websocket and running state before doing anything.

    Reports whether OBS is installed and where, whether it is currently
    running, whether the websocket server is enabled, and -- if reachable --
    the live scene, recording status and record directory.
    """
    report: dict = {"warnings": []}

    try:
        report["exe"] = str(paths.find_exe())
    except FileNotFoundError as exc:
        report["exe"] = None
        report["warnings"].append(str(exc))

    report["running_pids"] = paths.running_pids()

    try:
        ws = paths.websocket_settings()
        report["websocket_port"] = ws["port"]
        report["websocket_enabled"] = ws["enabled"]
        if not ws["enabled"]:
            report["warnings"].append(
                "obs-websocket server is disabled in config; obs_ensure_running "
                "will enable it, but OBS must then be (re)started."
            )
    except FileNotFoundError as exc:
        report["websocket_enabled"] = None
        report["warnings"].append(str(exc))
        return report

    try:
        c = _client()
    except client_mod.ObsUnavailable as exc:
        report["connected"] = False
        report["warnings"].append(str(exc))
        return report

    try:
        report["connected"] = True
        v = c.get_version()
        report["obs_version"] = v.obs_version
        report["websocket_version"] = v.obs_web_socket_version
        sl = c.get_scene_list()
        report["current_scene"] = sl.current_program_scene_name
        rs = c.get_record_status()
        report["recording"] = rs.output_active
        report["record_directory"] = c.get_record_directory().record_directory
    finally:
        c.disconnect()

    return report


@mcp.tool()
def obs_ensure_running(wait_s: float = 25.0) -> dict:
    """Launch OBS if it is not running, and wait until it accepts commands.

    Safe to call even if OBS is already up -- it just confirms and returns.
    """
    return client_mod.ensure_running(wait_s=wait_s)


# --------------------------------------------------------------- scenes/sources


@mcp.tool()
def obs_scenes() -> dict:
    """List scenes and report which one is currently live."""
    c = _client()
    try:
        sl = c.get_scene_list()
        return {
            "current": sl.current_program_scene_name,
            "scenes": [s["sceneName"] for s in sorted(sl.scenes, key=lambda s: s["sceneIndex"])],
        }
    finally:
        c.disconnect()


@mcp.tool()
def obs_set_scene(name: str) -> dict:
    """Switch the live (program) scene."""
    c = _client()
    try:
        c.set_current_program_scene(name)
        return {"current": name}
    finally:
        c.disconnect()


@mcp.tool()
def obs_sources(scene: str = "") -> dict:
    """List the capture sources in a scene: kind, visibility, size and position.

    Args:
        scene: Scene name. Defaults to the currently live scene.
    """
    c = _client()
    try:
        target = scene or c.get_scene_list().current_program_scene_name
        items = c.get_scene_item_list(target).scene_items
        return {
            "scene": target,
            "sources": [
                {
                    "id": it["sceneItemId"],
                    "name": it["sourceName"],
                    "kind": it["inputKind"],
                    "visible": it["sceneItemEnabled"],
                    "locked": it["sceneItemLocked"],
                    "width": it["sceneItemTransform"]["sourceWidth"],
                    "height": it["sceneItemTransform"]["sourceHeight"],
                }
                for it in items
            ],
        }
    finally:
        c.disconnect()


@mcp.tool()
def obs_set_source_visibility(source_id: int, visible: bool, scene: str = "") -> dict:
    """Show or hide a capture source. Get source_id from obs_sources.

    Args:
        scene: Scene the source belongs to. Defaults to the currently live scene.
    """
    c = _client()
    try:
        target = scene or c.get_scene_list().current_program_scene_name
        c.set_scene_item_enabled(target, source_id, visible)
        return {"scene": target, "source_id": source_id, "visible": visible}
    finally:
        c.disconnect()


# -------------------------------------------------------------------- record


@mcp.tool()
def obs_recording_start() -> dict:
    """Start recording the current scene to obs_probe's record_directory."""
    c = _client()
    try:
        c.start_record()
        return {"recording": True, "scene": c.get_scene_list().current_program_scene_name}
    finally:
        c.disconnect()


@mcp.tool()
def obs_recording_stop(flush_wait_s: float = 8.0) -> dict:
    """Stop recording and return the finished file's path.

    Briefly polls OBS after stopping, since the output file is still being
    flushed to disk for a moment after the stop call returns.
    """
    c = _client()
    try:
        result = c.stop_record()
        deadline = time.monotonic() + flush_wait_s
        while time.monotonic() < deadline:
            if not c.get_record_status().output_active:
                break
            time.sleep(0.3)
        path = result.output_path
        exists = Path(path).is_file() if path else False
        return {
            "path": path,
            "exists": exists,
            "bytes": Path(path).stat().st_size if exists else None,
        }
    finally:
        c.disconnect()


@mcp.tool()
def obs_recording_status() -> dict:
    """Current recording state: active, paused, elapsed time and size."""
    c = _client()
    try:
        rs = c.get_record_status()
        return {
            "active": rs.output_active,
            "paused": rs.output_paused,
            "timecode": rs.output_timecode,
            "bytes": rs.output_bytes,
        }
    finally:
        c.disconnect()


@mcp.tool()
def obs_set_record_directory(path: str) -> dict:
    """Change where OBS writes recordings.

    Point this at a project's raw-footage folder before recording, so capture
    lands next to (or directly reachable by) capcut_add_clip.
    """
    folder = Path(path)
    folder.mkdir(parents=True, exist_ok=True)
    c = _client()
    try:
        c.set_record_directory(str(folder))
        return {"record_directory": c.get_record_directory().record_directory}
    finally:
        c.disconnect()


@mcp.tool()
def obs_screenshot(out_path: str, source: str = "", width: int = 1280, height: int = 720) -> dict:
    """Grab a still from a source without starting a recording.

    Useful to confirm the right window/monitor is framed before recording for
    real, or as a lightweight way to check on-screen state while automating
    the browser.

    Args:
        source: Source name from obs_sources. Defaults to the first visible
            monitor/window/game capture source in the current scene.
    """
    c = _client()
    try:
        target = source
        if not target:
            scene = c.get_scene_list().current_program_scene_name
            visible = [
                it for it in c.get_scene_item_list(scene).scene_items
                if it["sceneItemEnabled"]
                and it["inputKind"] in {"monitor_capture", "window_capture", "game_capture"}
            ]
            if not visible:
                raise ValueError(
                    "No visible screen-capture source in the current scene; pass source= explicitly."
                )
            target = visible[0]["sourceName"]

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        c.save_source_screenshot(target, "png", str(out), width, height, -1)
        return {"path": str(out), "source": target, "bytes": out.stat().st_size}
    finally:
        c.disconnect()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
