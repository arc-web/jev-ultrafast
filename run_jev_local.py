#!/usr/bin/env python3
"""Run jev-ultrafast locally: URL + goal -> executed browser actions.

Chooser credentials come from ~/.config/jev/chooser.key (OpenRouter decisions route,
typesafe/jev-1.13). The browser is whatever exposes CDP on JEV_CDP_PORT, or a Chrome
for Testing instance launched for the purpose.

Usage:
  run_jev.py <url> "<goal>" [--max-steps N]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = int(os.environ.get("JEV_CDP_PORT", "9222"))
CHROME = Path.home() / ".hermes/tools/chromium-1208/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
KEY_FILE = Path.home() / ".config/jev/chooser.key"


def cdp_ws():
    for _ in range(2):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=3) as r:
                return json.loads(r.read())["webSocketDebuggerUrl"]
        except Exception:
            break
    if not CHROME.exists():
        raise SystemExit(f"no browser on :{PORT} and no Chrome for Testing at {CHROME}")
    subprocess.Popen(
        [str(CHROME), f"--remote-debugging-port={PORT}", "--user-data-dir=/tmp/jev-chrome-local",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2) as r:
                return json.loads(r.read())["webSocketDebuggerUrl"]
        except Exception:
            continue
    raise SystemExit("browser did not expose CDP")


def configure():
    key = KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""
    if not key:
        raise SystemExit("missing ~/.config/jev/chooser.key")
    os.environ.setdefault("CHOOSER_MODEL", "typesafe/jev-1.13")
    os.environ.setdefault("CHOOSER_API_KEY", key)
    os.environ.setdefault("TEXT_MODEL_API_KEY", key)
    os.environ.setdefault("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1")
    os.environ.setdefault("TEXT_MODEL", "inception/mercury-2.5")
    os.environ.setdefault("TEXT_MODEL_REASONING", "none")
    os.environ["BU_CDP_WS"] = cdp_ws()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    max_steps = 12
    if "--max-steps" in sys.argv:
        max_steps = int(sys.argv[sys.argv.index("--max-steps") + 1])
        args = [a for a in args if a != str(max_steps)]
    if len(args) < 2:
        raise SystemExit('usage: run_jev.py <url> "<goal>" [--max-steps N]')
    url, goal = args[0], args[1]
    configure()

    from jev_ultrafast.agent import Agent
    from jev_ultrafast.browser import StalePage

    agent = Agent(url, goal)
    trace, snap = [], None
    try:
        for _ in range(max_steps):
            try:
                snap = agent.command("tick")
            except StalePage:
                continue
            hist = snap.get("history") or []
            if hist and (not trace or trace[-1]["step"] != hist[-1]["step"]):
                h = hist[-1]
                trace.append({"step": h["step"], "action": h["action"], "kind": h["kind"],
                              "confidence": round(h.get("confidence") or 0, 3), "url": h.get("url")})
                print(f"[{h['step']}] {h['kind']}: {h['action']}  conf={h.get('confidence')}", file=sys.stderr)
            if snap.get("status") in ("done", "blocked"):
                break
    finally:
        try:
            agent.close()
        except Exception:
            pass

    print(json.dumps({"status": (snap or {}).get("status"), "url": url, "goal": goal,
                      "steps": trace, "final_url": ((snap or {}).get("page") or {}).get("url")}, indent=2))
    sys.exit(0 if (snap or {}).get("status") == "done" else 3)


if __name__ == "__main__":
    main()
