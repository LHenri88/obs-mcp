"""Run this first after installing. Never launches OBS and never changes any
setting -- it only reports what it finds.
"""

import sys

from obs_mcp import client, paths


def main() -> int:
    ok = True

    try:
        exe = paths.find_exe()
        print("OBS executable:      ", exe)
    except FileNotFoundError as exc:
        ok = False
        print("OBS executable:       NOT FOUND")
        print(f"  -> {exc}")

    pids = paths.running_pids()
    print("Running processes:   ", pids or "none")

    try:
        ws = paths.websocket_settings()
        print("Websocket port:      ", ws["port"])
        print("Websocket enabled:   ", ws["enabled"])
        if not ws["enabled"]:
            print("  -> Disabled in OBS's config. obs_ensure_running will enable it,")
            print("     but OBS must then be (re)started to pick that up.")
    except FileNotFoundError as exc:
        ok = False
        print("Websocket config:     NOT FOUND")
        print(f"  -> {exc}")
        print("Setup has issues -- see above.")
        return 1

    if pids:
        try:
            c = client.connect()
            v = c.get_version()
            print("Connected:            yes")
            print("OBS version:         ", v.obs_version)
            print("Websocket version:   ", v.obs_web_socket_version)
            c.disconnect()
        except client.ObsUnavailable as exc:
            ok = False
            print("Connected:            no")
            print(f"  -> {exc}")
    else:
        print("Connected:            OBS is not running -- call obs_ensure_running to start it")

    print("\n" + ("Setup looks good." if ok else "Setup has issues -- see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
