# obs-mcp

An MCP server that lets an LLM agent control local **OBS Studio** — launching
it, arranging scenes and sources, and recording — so it can capture its own
screen (testing a tool, browsing a site, demonstrating a workflow) as raw
footage, without a human touching OBS.

## Requirements

- **Windows only.** Process detection, install discovery and OBS's own
  websocket config path used here are all Windows-specific. There is no
  macOS/Linux support.
- Python 3.11+
- [OBS Studio](https://obsproject.com/) 28 or later (obs-websocket ships
  built in from that version on), installed and launched at least once
- ffmpeg is not required by this package itself, but is useful for inspecting
  the recordings it produces

## Why this exists

Producing a video autonomously means an agent needs to capture what it does
on screen as raw footage before editing it elsewhere — for example with
[capcut-mcp](https://github.com/LHenri88/capcut-mcp), a companion project
that edits the resulting recording inside CapCut. OBS already ships a
websocket control API (obs-websocket v5); this wraps it as 11 MCP tools and
adds the two things a human normally does by hand first: turning the
websocket server on, and launching OBS itself.

## How it works

Each tool opens a short-lived connection to OBS's websocket, does one thing,
and disconnects — OBS itself holds all the state, so there is nothing for
this server to keep alive between calls.

| Module | Role |
| --- | --- |
| `paths.py` | Find the OBS install and its websocket connection settings |
| `client.py` | Connect to a running OBS, or launch one from a cold start |
| `server.py` | The 11 MCP tools |

**OBS is not always running when the agent needs it.** `obs_ensure_running`
launches it if needed and blocks until the websocket actually accepts
requests, since the process starting and the websocket server becoming ready
are two different moments — polling `obs_probe` right after launch would
otherwise report a false negative.

**obs-websocket is disabled by default on most installs.** The first time
`obs_ensure_running` finds it disabled, it flips `server_enabled` on in OBS's
own config file and (re)launches OBS to pick that up.

## Tools

| Tool | Does |
| --- | --- |
| `obs_probe` | Install, websocket, running/connection state in one call |
| `obs_ensure_running` | Launch OBS if needed, block until it accepts commands |
| `obs_scenes` / `obs_set_scene` | List / switch scenes |
| `obs_sources` / `obs_set_source_visibility` | List / toggle capture sources in a scene |
| `obs_recording_start` / `obs_recording_stop` | Start/stop; stop returns the finished file's path |
| `obs_recording_status` | Active, paused, elapsed time, size |
| `obs_set_record_directory` | Point recordings at a project's raw-footage folder |
| `obs_screenshot` | Grab a still from a source without recording, to check framing |

## Session model

```
obs_probe                   check install + websocket + running state
obs_ensure_running           launch OBS if needed, wait for the websocket
obs_set_source_visibility      arrange the capture (screen, webcam, both)
obs_recording_start          ...browse / demo / test something...
obs_recording_stop             -> file path, ready for the next editing step
```

## A timing detail worth knowing

`StopRecord`'s own response returns the output file's path before the file
has actually finished being flushed to disk. `obs_recording_stop` polls OBS's
recording status for a few seconds after stopping and only returns once the
output has gone inactive, so the path it hands back is safe to open
immediately.

## Install

```bash
uv venv --python 3.13
uv pip install -e .
```

Register with Claude Code:

```bash
claude mcp add obs -s user -- "<path-to-repo>/.venv/Scripts/obs-mcp.exe"
```

(On Windows/PowerShell, run this from a shell where `--` isn't swallowed —
Git Bash works; if using PowerShell directly, use `claude --%` escaping or
call the venv's `obs-mcp.exe` path directly as shown.)

If OBS isn't found automatically (`obs_probe` reports it missing), set
`OBS_MCP_EXE` to the full path of `obs64.exe`.

## Verify your install

```bash
.venv/Scripts/python.exe scripts/verify_setup.py   # install/websocket state -- safe, makes no changes
```

## Known limits

- One scene/source model: no per-source audio gain, filters or transform
  editing here — only visibility. Recording always captures whatever is live
  in the current scene; switch scenes or toggle sources first if a specific
  arrangement is needed.
- No streaming, replay buffer or virtual camera tools yet — recording only.
- `obs_screenshot` picks the first visible monitor/window/game-capture source
  in the scene when `source` is omitted; pass it explicitly for a specific
  camera or window.

## Contributing

Issues and PRs welcome. If you're adding a tool that calls a new
obs-websocket request, please confirm its real response shape against a
running OBS instance (the `obsws-python` client's field names do not always
match the raw protocol's camelCase names) rather than guessing from the
obs-websocket protocol docs alone.

## License

MIT — see [LICENSE](LICENSE).
