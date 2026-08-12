#!/usr/bin/env python3
"""Run the LCARS panel virtually with a live browser viewer.

    python3 virtual/run_virtual.py [--port N] [--env FILE] [--no-respawn]
                                   [--hold] [-- PANEL_ARGS...]

Everything after `--` is passed to the panel itself (e.g. `-- --debug`).
The MQTT `restart` control command makes the panel exit nonzero; by default
we then re-exec ourselves — emulating systemd's Restart=always with a
genuinely fresh process, exactly like on the device.
"""
import argparse
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=None,
                        help="HTTP port (default: VIRTUAL_HTTP_PORT or 8724)")
    parser.add_argument("--bind", default=None,
                        help="HTTP bind address (default: VIRTUAL_HTTP_BIND or 127.0.0.1)")
    parser.add_argument("--env", default=None,
                        help="env file (default: virtual/panel.env, else panel.env.example)")
    parser.add_argument("--no-respawn", action="store_true",
                        help="do not re-exec after a nonzero panel exit (MQTT restart command)")
    parser.add_argument("--hold", action="store_true",
                        help="keep the HTTP server alive after the panel exits cleanly")
    if "--" in argv:
        split = argv.index("--")
        args = parser.parse_args(argv[:split])
        panel_args = argv[split + 1:]
    else:
        args = parser.parse_args(argv)
        panel_args = []
    return args, panel_args


def main():
    args, panel_args = parse_args(sys.argv[1:])

    from virtual.harness import VirtualPanel
    vp = VirtualPanel(env_file=args.env)

    port = args.port or int(os.environ.get("VIRTUAL_HTTP_PORT", "8724"))
    bind = args.bind or os.environ.get("VIRTUAL_HTTP_BIND", "127.0.0.1")

    from virtual import server
    server.start_in_thread(vp, bind, port)
    vp.start_state_watcher()
    print("virtual: viewer at http://%s:%d" % (bind, port), flush=True)

    panel = vp.import_panel(panel_args)
    exit_code = 0
    try:
        panel.main()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0
    print("virtual: panel exited with code %s" % exit_code, flush=True)

    if exit_code != 0 and not args.no_respawn:
        # Emulate systemd Restart=always (RestartSec=2). A fresh process is
        # required: panel module state is not safely reloadable in-process.
        print("virtual: respawning in 2s (systemd Restart=always emulation)...",
              flush=True)
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    if args.hold:
        print("virtual: panel finished; holding HTTP server (Ctrl+C to quit)", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
