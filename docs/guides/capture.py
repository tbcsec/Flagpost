#!/usr/bin/env python3
"""Capture the user-guide screenshots from a demo-mode dev stack.

Drives headless Chromium over CDP, signs in as the demo persona each guide
documents (participant / judge / admin), and clips each shot to the surface's
own bounding box at 2x for print sharpness. PNGs land in
``<guide>/assets/``; chapters reference them as ``assets/<name>.png``.

Usage (stack on :3000/:8000, e.g. ``docker compose -f docker-compose.dev.yml up``):
    python capture.py                 # all guides
    python capture.py judge admin     # a subset

Needs httpx + websockets (both in backend/.venv). If the demo competition's
hourly-reset window has lapsed ("competition has ended"), start it again as
admin first — see README.
"""
import asyncio, base64, json, shutil, signal, subprocess, sys
from pathlib import Path

import httpx, websockets

BASE = "http://localhost:3000"
ROOT = Path(__file__).resolve().parent
# Snap chromium may only write inside its own area — a profile elsewhere is
# silently replaced with the default (and collides with the user's browser).
PROFILE = Path.home() / "snap" / "chromium" / "common" / "fp-guide-capture"
PORT = 9223
VIEW_W, VIEW_H, DPR = 1440, 900, 2
MAIN = "#main-content"

# Per-shot prep snippets (run after navigation, before the screenshot).
SELECT_FIRST_MANAGE_ROW = """
  (() => {
    const row = document.querySelector('#main-content ul button');
    if (row) row.click();
    return !!row;
  })()"""

OPEN_UNSOLVED_CARD = """
  (() => {
    const cards = [...document.querySelectorAll(
      '#main-content div[class*="grid-cols"] > button')];
    const card = cards.find(c => !c.textContent.includes('Solved')) || cards[0];
    if (!card) return false;
    card.click();
    return true;
  })()"""

# guide -> (persona, [ (name, path, prep_js, selector, pad) ])
GUIDES = {
    "competitor": ("participant", [
        ("login",            "/login",             "LOGIN_CARD", None, 18),
        ("challenges",       "/challenges",        None, MAIN, 14),
        ("challenge-dialog", "/challenges",        OPEN_UNSOLVED_CARD, "[role=dialog]", 10),
        ("scoreboard",       "/scoreboard",        None, MAIN, 14),
        ("support",          "/support",           None, MAIN, 14),
    ]),
    "judge": ("judge", [
        ("dashboard",        "/",                  None, MAIN, 14),
        ("manage",           "/challenges/manage", SELECT_FIRST_MANAGE_ROW, MAIN, 14),
        ("settings",         "/settings",          None, MAIN, 14),
        ("tickets",          "/support",           None, MAIN, 14),
    ]),
    "admin": ("admin", [
        ("overview",         "/admin",             None, MAIN, 14),
        ("users",            "/admin/users",       None, MAIN, 14),
        ("roles",            "/admin/roles",       None, MAIN, 14),
        ("site-settings",    "/admin/settings",    None, MAIN, 14),
        ("competitions",     "/admin/competitions", None, MAIN, 14),
        ("pages",            "/admin/pages",       None, MAIN, 14),
        ("audit-log",        "/admin/events",      None, MAIN, 14),
    ]),
}

_id = 0
async def cdp(ws, method, params=None):
    global _id
    _id += 1
    await ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == _id:
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg.get("result", {})

async def evaljs(ws, expr):
    r = await cdp(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("value")

async def goto(ws, url, settle=3.0):
    await cdp(ws, "Page.navigate", {"url": url})
    await asyncio.sleep(settle)

async def shot(ws, out_dir, name, selector, pad):
    clip = None
    if selector:
        rect = await evaljs(ws, f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{x: r.x, y: r.y, w: r.width, h: r.height}};
        }})()""")
        if rect:
            x = max(rect["x"] - pad, 0); y = max(rect["y"] - pad, 0)
            clip = {"x": x, "y": y,
                    "width": min(rect["w"] + 2 * pad, VIEW_W - x),
                    "height": min(rect["h"] + 2 * pad, VIEW_H - y), "scale": 1}
        else:
            print(f"  !! {name}: {selector!r} not found — full viewport")
    params = {"format": "png"}
    if clip: params["clip"] = clip
    r = await cdp(ws, "Page.captureScreenshot", params)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.png"
    out.write_bytes(base64.b64decode(r["data"]))
    print(f"  -> {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")

SET_NATIVE = """
function setNative(el, value) {
  const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  s.call(el, value);
  el.dispatchEvent(new Event('input', {bubbles: true}));
}
"""

async def sign_out(ws):
    """Hard sign-out between personas: cookies + storage, then a fresh load."""
    await cdp(ws, "Network.clearBrowserCookies")
    await goto(ws, f"{BASE}/login", settle=1.5)
    await evaljs(ws, "localStorage.clear(), sessionStorage.clear(), true")
    await goto(ws, f"{BASE}/login", settle=2.5)

async def sign_in(ws, username):
    ok = await evaljs(ws, SET_NATIVE + f"""
      (() => {{
        const inputs = document.querySelectorAll('form input');
        if (inputs.length < 2) return 'inputs missing';
        setNative(inputs[0], {json.dumps(username)});
        setNative(inputs[1], 'password');
        const btn = [...document.querySelectorAll('form button')].find(b => b.type === 'submit');
        if (!btn) return 'no submit';
        btn.click();
        return 'submitted';
      }})()""")
    await asyncio.sleep(4)
    print(f"  sign-in as {username}: {ok} (now at {await evaljs(ws, 'location.pathname')})")

async def capture_guide(ws, guide):
    persona, shots = GUIDES[guide]
    out_dir = ROOT / guide / "assets"
    print(f"── {guide} (as {persona}) ──")
    await sign_out(ws)

    for name, path, prep, selector, pad in shots:
        # The login shot is taken while still signed out.
        if prep == "LOGIN_CARD":
            await goto(ws, f"{BASE}{path}", settle=3)
            await evaljs(ws, """
              (() => {
                const card = document.querySelector('form').closest('div[class*="rounded"]');
                if (card) card.id = '__login_card';
                return !!card;
              })()""")
            await shot(ws, out_dir, name, "#__login_card", pad)
            await sign_in(ws, persona)
            continue
        if name == shots[0][0] and prep != "LOGIN_CARD":
            await sign_in(ws, persona)
        await goto(ws, f"{BASE}{path}", settle=3)
        if prep and prep != "LOGIN_CARD":
            done = await evaljs(ws, prep)
            print(f"  prep {name}: {done}")
            await asyncio.sleep(2.5)
        await shot(ws, out_dir, name, selector, pad)

async def main():
    guides = sys.argv[1:] or list(GUIDES)
    for g in guides:
        if g not in GUIDES:
            print(f"unknown guide {g!r} (choose from {', '.join(GUIDES)})"); return 2

    if PROFILE.exists(): shutil.rmtree(PROFILE)
    proc = subprocess.Popen(
        ["/usr/bin/chromium-browser", "--headless=new", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROFILE}", f"--window-size={VIEW_W},{VIEW_H}",
         "--no-first-run", "--disable-gpu", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        async with httpx.AsyncClient() as client:
            for _ in range(40):
                try:
                    targets = (await client.get(f"http://localhost:{PORT}/json")).json()
                    pages = [t for t in targets if t.get("type") == "page"]
                    if pages:
                        ws_url = pages[0]["webSocketDebuggerUrl"]; break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
        if not ws_url:
            print("chromium debug endpoint never came up"); return 1

        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            await cdp(ws, "Page.enable")
            await cdp(ws, "Runtime.enable")
            await cdp(ws, "Network.enable")
            await cdp(ws, "Emulation.setDeviceMetricsOverride",
                      {"width": VIEW_W, "height": VIEW_H, "deviceScaleFactor": DPR, "mobile": False})
            for guide in guides:
                await capture_guide(ws, guide)
            # Ask the browser to shut itself down — snap confinement blocks
            # signalling it from outside, so SIGTERM below may be denied.
            try:
                await ws.send(json.dumps({"id": 999999, "method": "Browser.close"}))
            except Exception:
                pass
        return 0
    finally:
        try: proc.send_signal(signal.SIGTERM)
        except Exception: pass
        try: proc.wait(timeout=5)
        except Exception: pass
        shutil.rmtree(PROFILE, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
