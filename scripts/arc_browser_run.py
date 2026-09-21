#!/usr/bin/env python3
"""Run one browser goal with the local Chrome and jev-ultrafast.

Reads its keys from OpenBao at run time, starts the browser if it is not up,
runs one goal, writes a trace, and stops the browser again unless asked to keep it.

Usage:
    browser_agent_run.py --url https://example.com --goal "Read the page heading"
    browser_agent_run.py --url ... --goal ... --keep-browser --screenshots

Keys (never printed, never written to a file):
    hermes/openrouter-key   via the OpenBao sidecar at 127.0.0.1:8100
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHROME = os.environ.get("JEV_CHROME", "/opt/data/tools/pw/chromium-1243/chrome-linux64/chrome")
CDP_PORT = int(os.environ.get("JEV_CDP_PORT", "9333"))
PROFILE = os.environ.get("JEV_PROFILE_DIR", "/opt/data/tmp/cdp-full")
BH_HOME = os.environ.get("JEV_BH_HOME", "/opt/data/tmp/bh-home")
TRACE_DIR = Path(os.environ.get("JEV_TRACE_DIR", "/opt/data/state/browser-traces"))
LOG = "/opt/data/tmp/chrome-run.log"
BAO = "http://127.0.0.1:8100/v1/secret/data/"


def vault(path: str) -> str:
    req = urllib.request.Request(BAO + path, headers={"User-Agent": "jev-runner"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())["data"]["data"]["value"]


def browser_up() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def start_browser() -> subprocess.Popen | None:
    if browser_up():
        print("browser: already up")
        return None
    Path(PROFILE).mkdir(parents=True, exist_ok=True)
    # A killed browser leaves the profile locked, and the next start refuses.
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = Path(PROFILE) / lock
        try:
            if p.is_symlink() or p.exists():
                p.unlink()
                print(f"browser: cleared stale {lock}")
        except OSError as exc:
            print(f"browser: could not clear {lock}: {exc}")
    log = open(LOG, "ab")
    proc = subprocess.Popen(
        [
            CHROME, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
            f"--remote-debugging-port={CDP_PORT}", "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE}", "about:blank",
        ],
        stdout=log, stderr=log, start_new_session=True,
    )
    for _ in range(50):
        time.sleep(0.5)
        if browser_up():
            print(f"browser: started (pid {proc.pid}, port {CDP_PORT})")
            return proc
    raise SystemExit(f"browser did not come up; see {LOG}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--goal", required=True)
    ap.add_argument("--keep-browser", action="store_true", help="leave the browser running")
    ap.add_argument("--screenshots", action="store_true", help="save a frame per step")
    ap.add_argument("--chooser-model", default=os.environ.get("JEV_CHOOSER_MODEL", "qwen/qwen3.7-flash"))
    ap.add_argument("--text-model", default=os.environ.get("JEV_TEXT_MODEL", "inception/mercury-2.5"))
    args = ap.parse_args()

    key = vault("hermes/openrouter-key")
    os.environ.update(
        {
            "BH_TELEMETRY": "0",
            "BH_HOME": BH_HOME,
            "BU_NAME": f"jev-{int(time.time())}",
            "BU_CDP_URL": f"http://127.0.0.1:{CDP_PORT}",
            "TEXT_MODEL_API_KEY": key,
            "TEXT_MODEL_BASE_URL": "https://openrouter.ai/api/v1",
            "TEXT_MODEL": args.text_model,
            "TEXT_MODEL_REASONING": "none",
            "CHOOSER_API_KEY": key,
            "CHOOSER_BASE_URL": "https://openrouter.ai/api/v1",
            "CHOOSER_MODEL": args.chooser_model,
            "CHOOSER_PROVIDER": os.environ.get("CHOOSER_PROVIDER", "openrouter"),
            "CHOOSER_JSON_MODE": os.environ.get("CHOOSER_JSON_MODE", "1"),
            "TEXT_JSON_MODE": os.environ.get("TEXT_JSON_MODE", "0"),
            "CHOOSER_REASONING": os.environ.get("CHOOSER_REASONING", "none"),
        }
    )
    # Page fetches must not route through the Browser Use service.
    os.environ.pop("BROWSER_USE_API_KEY", None)

    proc = start_browser()
    started = time.time()
    trace = {"url": args.url, "goal": args.goal, "started_at": datetime.now(timezone.utc).isoformat(), "steps": []}
    status, last_title, last_url = "unknown", "", ""
    seen_steps = set()
    try:
        from jev_ultrafast import Agent

        record_dir = None
        if args.screenshots:
            record_dir = TRACE_DIR / f"frames-{int(started)}"
        with Agent(args.url, args.goal, record_dir=record_dir, screenshots=args.screenshots) as agent:
            for state in agent.run():
                last = state["history"][-1] if state["history"] else None
                if last and last["step"] not in seen_steps:
                    seen_steps.add(last["step"])
                    trace["steps"].append(
                        {
                            "step": last["step"],
                            "action": last["action"],
                            "kind": last["kind"],
                            "operation": last["operation"],
                            "target": last["target"],
                            "confidence": last["confidence"],
                            "text": last["text"],
                            "page_changed": last["page_changed"],
                            "elapsed_ms": last["elapsed_ms"],
                            "usage": last.get("usage"),
                        }
                    )
                    print(f"  {last['step']:>2}. {last['operation']:<9} {str(last['action'])[:70]} ({last['elapsed_ms']} ms)")
                status = state["status"]
                last_title = (state.get("page") or {}).get("title") or last_title
                last_url = (state.get("page") or {}).get("url") or last_url
            trace["decisions"] = [
                {"operation": d.get("operation"), "choice": d.get("choice"), "latency_ms": d.get("latency_ms"),
                 "usage": d.get("usage"), "model": d.get("model")}
                for d in agent.state.get("decisions", [])
            ]
            trace["text_calls"] = agent.state.get("text_calls", [])
            trace["elapsed_ms"] = agent.state.get("elapsed_ms")
    except Exception as exc:  # a failed run is a result, not a crash
        status = f"error: {type(exc).__name__}: {exc}"
        print("run error:", status)
    finally:
        if proc is not None and not args.keep_browser:
            proc.terminate()
            print("browser: stopped")
        elif proc is None:
            print("browser: left as found")

    trace["status"] = status
    trace["page_title"] = last_title
    trace["final_url"] = last_url
    trace["wall_seconds"] = round(time.time() - started, 2)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{int(started)}-{args.url.split('//')[-1].split('/')[0].replace('.', '-')}.json"
    path.write_text(json.dumps(trace, indent=2))
    tokens = sum((s.get("usage") or {}).get("total_tokens", 0) or 0 for s in trace["steps"])
    print(json.dumps({
        "status": status, "steps": len(trace["steps"]), "wall_seconds": trace["wall_seconds"],
        "page_title": last_title, "final_url": last_url, "trace": str(path), "tokens_on_text_calls": tokens,
    }))
    return 0 if status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
