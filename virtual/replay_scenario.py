#!/usr/bin/env python3
"""Replay a virtual-panel scenario against the REAL device via mosquitto_pub.

    python3 virtual/replay_scenario.py virtual/scenarios/golden_screens.json \
        --host homeassistant.local [--user U --password P]

MQTT steps are published with the same relative timing as the virtual run.
Touch steps become interactive prompts (device touch cannot be injected).
Capture steps publish the panel's `screenshot` control command; grab the PNG
from the device afterwards:

    scp <user>@<panel-host>:lcars_panel_screenshots/<newest>.png device.png
    python3 virtual/snapshot.py compare virtual/out/<name>/NNN_x.png device.png

Broker chaos steps obviously can't be automated against a production broker;
they print manual instructions instead (e.g. restart the Mosquitto add-on).
"""
import argparse
import json
import shutil
import subprocess
import sys
import time


def mosquitto_pub(args, topic, payload, retain=False):
    cmd = ["mosquitto_pub", "-h", args.host, "-p", str(args.port),
           "-t", topic, "-m", payload]
    if retain:
        cmd.append("-r")
    if args.user:
        cmd += ["-u", args.user]
    if args.password:
        cmd += ["-P", args.password]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("scenario")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--control-prefix", default="lcars/alert-panel/",
                        help="control topic prefix on the device")
    args = parser.parse_args()

    if shutil.which("mosquitto_pub") is None:
        sys.exit("mosquitto_pub not found (apt install mosquitto-clients)")

    with open(args.scenario, "r", encoding="utf-8") as fh:
        scenario = json.load(fh)
    print("Replaying scenario '%s' against %s" % (scenario.get("name"), args.host))

    for i, step in enumerate(scenario.get("steps", [])):
        do = step["do"]
        if do == "wait":
            time.sleep(step.get("ms", 100) / 1000.0)
        elif do == "mqtt":
            payload = step.get("payload", "")
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            print("  [%d] publish %s" % (i, step["topic"]))
            mosquitto_pub(args, step["topic"], payload, bool(step.get("retain", False)))
            time.sleep(0.2)
        elif do == "touch":
            input("  [%d] TOUCH the device screen at approx (%s, %s), then press Enter..."
                  % (i, step["x"], step["y"]))
        elif do in ("wait_frame", "wait_state"):
            time.sleep(1.0)
        elif do == "broker_drop":
            input("  [%d] MANUAL: briefly interrupt the device's network or skip "
                  "(Enter to continue)..." % i)
        elif do == "broker_restart":
            input("  [%d] MANUAL: restart the Mosquitto broker now (e.g. HA UI -> "
                  "Add-ons -> Mosquitto -> Restart), wait for the panel to "
                  "reconnect, then press Enter..." % i)
        elif do == "capture":
            print("  [%d] requesting device screenshot ('%s')"
                  % (i, step.get("name", "")))
            mosquitto_pub(args, args.control_prefix + "screenshot", "now")
            time.sleep(1.0)
        else:
            print("  [%d] skipping unknown step %r" % (i, do))

    print("Done. Fetch the screenshot(s) from ~/lcars_panel_screenshots/ on the "
          "device and compare with `snapshot.py compare`.")


if __name__ == "__main__":
    main()
