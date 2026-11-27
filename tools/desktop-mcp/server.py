#!/usr/bin/env python3
"""ninelives-desktop: a tiny MCP server (stdio, no dependencies) that lets a coding agent check the
cat on the real desktop: take a screenshot (cropped and scaled), and show a `kitten panel` for a
limited time. Owner-approved on 2026-11-27 ("add a mcp layer so you can test it yourself").

It never clicks, types or moves the pointer, so it can't take the keyboard or the mouse. Panels it
starts always use --focus-policy=not-allowed and stop on their own (60 s at most).

  claude mcp add --scope local ninelives-desktop -- python3 tools/desktop-mcp/server.py

Tools: outputs, screenshot, panel_show, panel_stop. Screenshots use cosmic-screenshot (COSMIC) or
grim (other wlroots desktops); cropping and scaling use ffmpeg. Files go to $NL_DESKTOP_DIR
(default: a folder under $XDG_RUNTIME_DIR, else a fresh private one from mkdtemp), never into the
repo; a folder that isn't this user's alone (owner, mode 0700) is refused.
"""
import base64
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import stat
import sys
import tempfile
import time

# where screenshots and panel logs go: $NL_DESKTOP_DIR, else a folder in $XDG_RUNTIME_DIR, else a
# fresh private folder from mkdtemp (a fixed name in /tmp could be made beforehand by someone else)
OUT_DIR = os.environ.get("NL_DESKTOP_DIR") or (
    os.path.join(os.environ["XDG_RUNTIME_DIR"], "ninelives-desktop") if os.environ.get("XDG_RUNTIME_DIR") else "")
KITTEN = shutil.which("kitten") or os.path.expanduser("~/.local/kitty.app/bin/kitten")
PANEL_MAX = 60
_panels: dict = {}          # pid -> Popen

TOOLS = [
    {"name": "outputs",
     "description": "List the monitors (name, position, size) so screenshots and panels can be aimed.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "screenshot",
     "description": "Screenshot of the whole desktop (all monitors, in global coordinates), optionally "
                    "cropped to a rectangle and scaled down. Returns the image and its saved path.",
     "inputSchema": {"type": "object", "properties": {
         "x": {"type": "integer"}, "y": {"type": "integer"},
         "width": {"type": "integer"}, "height": {"type": "integer"},
         "max_width": {"type": "integer", "description": "scale down to at most this width (default 1280)"},
     }}},
    {"name": "panel_show",
     "description": "Show a kitten panel (layer-shell overlay, never takes focus) running a command or "
                    "printing text, for at most 60 s. Returns its pid and log path.",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "text to print (used when no command is given)"},
         "command": {"type": "array", "items": {"type": "string"}},
         "seconds": {"type": "integer", "description": "how long it stays (1-60, default 15)"},
         "edge": {"type": "string", "description": "none (default), top, bottom, left, right, center"},
         "layer": {"type": "string", "description": "overlay (default), top, bottom, background"},
         "lines": {"type": "integer"}, "columns": {"type": "integer"},
         "margin_left": {"type": "integer"}, "margin_top": {"type": "integer"},
         "margin_right": {"type": "integer"}, "margin_bottom": {"type": "integer"},
         "output": {"type": "string", "description": "monitor name, e.g. DP-1"},
         "opacity": {"type": "number", "description": "background_opacity, default 0.85"},
         "extra": {"type": "array", "items": {"type": "string"}, "description": "more kitten panel options"},
     }}},
    {"name": "panel_stop",
     "description": "Stop panels started by panel_show (one pid, or all).",
     "inputSchema": {"type": "object", "properties": {"pid": {"type": "integer"}}}},
]


def _text(s: str) -> dict:
    return {"type": "text", "text": s}


def outputs() -> list:
    try:
        raw = subprocess.run(["cosmic-randr", "list"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return [_text(f"cosmic-randr failed: {e}")]
    raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    found, name = [], None
    for line in raw.splitlines():
        m = re.match(r"^(\S+) \((enabled|disabled)\)", line)
        if m:
            name = {"name": m.group(1), "enabled": m.group(2) == "enabled"}
            found.append(name)
        elif name is not None:
            p = re.match(r"\s+Position:\s*(-?\d+),(-?\d+)", line)
            if p:
                name["x"], name["y"] = int(p.group(1)), int(p.group(2))
            c = re.match(r"\s+(\d+)x(\d+) @ .*\(current\)", line)
            if c:
                name["width"], name["height"] = int(c.group(1)), int(c.group(2))
            s = re.match(r"\s+Scale:\s*(\d+)%", line)
            if s:
                name["scale"] = int(s.group(1)) / 100
    return [_text(json.dumps(found, indent=1))]


def out_dir() -> str:
    """The output folder, private to this user: made with mode 0700, and an existing one is used only
    if it's a real folder (not a link) owned by this user that nobody else can read or write."""
    global OUT_DIR
    if not OUT_DIR:
        OUT_DIR = tempfile.mkdtemp(prefix="ninelives-desktop-")
        return OUT_DIR
    os.makedirs(OUT_DIR, mode=0o700, exist_ok=True)
    st = os.lstat(OUT_DIR)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PermissionError(f"{OUT_DIR} is not a private folder of this user (mode "
                              f"{stat.S_IMODE(st.st_mode):o}, owner {st.st_uid}); not saving pixels there")
    return OUT_DIR


# kitten panel options that would let a panel take the keyboard, or outlive its timeout and
# panel_stop (detached, or shown by an existing single-instance kitty), or end the options early
PANEL_REFUSED = ("focus-policy", "grab-keyboard", "single-instance", "instance-group", "detach")


def _refused_option(opt: str) -> bool:
    return opt in ("--", "-1") or opt.startswith("-1=") or any(r in opt for r in PANEL_REFUSED)


def screenshot(args: dict) -> list:
    try:
        out = out_dir()
    except OSError as e:
        return [_text(f"screenshot refused: {e}")]
    before = set(glob.glob(os.path.join(out, "*.png")))
    if shutil.which("cosmic-screenshot"):
        cmd = ["cosmic-screenshot", "--interactive=false", "--modal=false", "--notify=false",
               "--save-dir", out]
    elif shutil.which("grim"):
        cmd = ["grim", os.path.join(out, f"shot-{int(time.time() * 1000)}.png")]
    else:
        return [_text("no screenshot tool (cosmic-screenshot or grim) found")]
    try:
        subprocess.run(cmd, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return [_text(f"screenshot failed: {e}")]
    new = sorted(set(glob.glob(os.path.join(out, "*.png"))) - before, key=os.path.getmtime)
    new = [p for p in new if not os.path.basename(p).startswith("view-")]
    if not new:
        return [_text("screenshot failed: no file was written")]
    src = new[-1]
    filters = []
    if all(k in args for k in ("x", "y", "width", "height")):
        filters.append(f"crop={int(args['width'])}:{int(args['height'])}:{int(args['x'])}:{int(args['y'])}")
    max_w = int(args.get("max_width") or 1280)
    filters.append(f"scale='min({max_w},iw)':-2")
    view = os.path.join(out, "view-" + os.path.basename(src))
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", ",".join(filters), view],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return [_text(f"crop/scale failed: {r.stderr.strip()[:300]}")]
    with open(view, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return [{"type": "image", "data": data, "mimeType": "image/png"},
            _text(f"full: {src}\nview: {view}")]


def panel_show(args: dict) -> list:
    seconds = max(1, min(PANEL_MAX, int(args.get("seconds") or 15)))
    cmd = ["timeout", str(seconds), KITTEN, "panel", "--config", "NONE",
           "--focus-policy=not-allowed",          # never takes the keyboard: not negotiable
           f"--edge={args.get('edge') or 'none'}", f"--layer={args.get('layer') or 'overlay'}",
           "--override", f"background_opacity={float(args.get('opacity', 0.85))}",
           "--app-id", "ninelives-desktop-test"]
    for key in ("lines", "columns"):
        if args.get(key):
            cmd.append(f"--{key}={int(args[key])}")
    for key in ("margin_left", "margin_top", "margin_right", "margin_bottom"):
        if args.get(key) is not None:
            cmd.append(f"--{key.replace('_', '-')}={int(args[key])}")
    if args.get("output"):
        cmd.append(f"--output-name={args['output']}")
    for opt in args.get("extra") or []:
        if _refused_option(str(opt)):
            return [_text(f"refused: {opt} (the panel never takes the keyboard, keeps its own process "
                          "and stops on its own)")]
        cmd.append(str(opt))
    cmd.append("--")                    # the command's own words are never read as panel options
    if args.get("command"):
        cmd += [str(c) for c in args["command"]]
    else:
        cmd += ["sh", "-c", 'printf "%b" "$1"; sleep 3600', "sh", str(args.get("text") or "=^.^= hello")]
    try:
        log = os.path.join(out_dir(), f"panel-{int(time.time() * 1000)}.log")
    except OSError as e:
        return [_text(f"panel refused: {e}")]
    with open(log, "wb") as out:
        p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    _panels[p.pid] = p
    time.sleep(1.0)
    state = "running" if p.poll() is None else f"exited {p.returncode}"
    with open(log, errors="replace") as f:
        head = f.read()[-600:]
    return [_text(json.dumps({"pid": p.pid, "state": state, "seconds": seconds, "log": log,
                              "log_tail": head}, indent=1))]


def panel_stop(args: dict) -> list:
    pids = [int(args["pid"])] if args.get("pid") else list(_panels)
    stopped = []
    for pid in pids:
        p = _panels.pop(pid, None)
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                stopped.append(pid)
            except OSError:
                pass
    return [_text(f"stopped: {stopped or 'nothing running'}")]


def call(name: str, args: dict) -> list:
    if name == "outputs":
        return outputs()
    if name == "screenshot":
        return screenshot(args)
    if name == "panel_show":
        return panel_show(args)
    if name == "panel_stop":
        return panel_stop(args)
    raise KeyError(name)


def main() -> None:
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:              # a notification (e.g. notifications/initialized)
            continue
        if method == "initialize":
            result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "ninelives-desktop", "version": "0.1"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            try:
                result = {"content": call(params.get("name", ""), params.get("arguments") or {})}
            except KeyError:
                result = {"content": [_text("unknown tool")], "isError": True}
            except Exception as e:      # report, don't die
                result = {"content": [_text(f"error: {e}")], "isError": True}
        elif method == "ping":
            result = {}
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                         "error": {"code": -32601, "message": "method not found"}}) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    finally:
        panel_stop({})
