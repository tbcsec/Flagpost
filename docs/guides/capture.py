#!/usr/bin/env python3
"""Capture competitor-view screenshots for the user guides via headless Chromium CDP."""
import asyncio, base64, json, shutil, signal, subprocess, sys, time
from pathlib import Path

import httpx, websockets

BASE = "http://localhost:3000"
OUT = Path("/home/tom/Documents/projects/flagpost/docs/guides/competitor/assets")
# Snap chromium may only write inside its own area — a profile elsewhere is
# silently replaced with the default (and collides with the user's browser).
PROFILE = Path.home() / "snap" / "chromium" / "common" / "fp-guide-capture"
PORT = 9223
VIEW_W, VIEW_H, DPR = 1440, 900, 2

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

async def goto(ws, url, settle=2.5):
    await cdp(ws, "Page.navigate", {"url": url})
    await asyncio.sleep(settle)

async def shot(ws, name, selector=None, pad=14):
    if selector:
        rect = await evaljs(ws, f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{x: r.x, y: r.y, w: r.width, h: r.height}};
        }})()""")
        if not rect:
            print(f"  !! {name}: selector {selector!r} not found — full viewport")
            clip = None
        else:
            x = max(rect["x"] - pad, 0); y = max(rect["y"] - pad, 0)
            clip = {"x": x, "y": y,
                    "width": min(rect["w"] + 2 * pad, VIEW_W - x),
                    "height": min(rect["h"] + 2 * pad, VIEW_H - y), "scale": 1}
    else:
        clip = None
    params = {"format": "png"}
    if clip: params["clip"] = clip
    r = await cdp(ws, "Page.captureScreenshot", params)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.png"
    out.write_bytes(base64.b64decode(r["data"]))
    print(f"  -> {out.name}  ({out.stat().st_size // 1024} KB)")

SET_NATIVE = """
function setNative(el, value) {
  const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  s.call(el, value);
  el.dispatchEvent(new Event('input', {bubbles: true}));
}
"""

async def main():
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
            await cdp(ws, "Emulation.setDeviceMetricsOverride",
                      {"width": VIEW_W, "height": VIEW_H, "deviceScaleFactor": DPR, "mobile": False})

            # ── login page shot (signed out) ──
            await goto(ws, f"{BASE}/login", settle=3)
            # The sign-in *card* (heading + form + register line), not the bare
            # form — the form alone slices the card's header and footer text.
            await evaljs(ws, """
              (() => {
                const card = document.querySelector('form').closest('div[class*="rounded"]');
                if (card) card.id = '__login_card';
                return !!card;
              })()""")
            await shot(ws, "login", selector="#__login_card", pad=18)

            # ── sign in as the demo participant ──
            ok = await evaljs(ws, SET_NATIVE + """
              (() => {
                const inputs = document.querySelectorAll('form input');
                if (inputs.length < 2) return 'inputs missing';
                setNative(inputs[0], 'participant');
                setNative(inputs[1], 'password');
                const btn = [...document.querySelectorAll('form button')].find(b => b.type === 'submit');
                if (!btn) return 'no submit';
                btn.click();
                return 'submitted';
              })()""")
            print(f"  login: {ok}")
            await asyncio.sleep(4)
            print("  url now:", await evaljs(ws, "location.pathname"))

            # ── challenges grid ──
            await goto(ws, f"{BASE}/challenges", settle=3)
            await shot(ws, "challenges", selector="#main-content")

            # ── challenge dialog (open the first card) ──
            clicked = await evaljs(ws, """
              (() => {
                // Cards are the direct button children of the card grid —
                // NOT the category chips (their own flex row). Prefer an
                // unsolved card so the dialog shows the flag-entry form.
                const cards = [...document.querySelectorAll(
                  '#main-content div[class*="grid-cols"] > button')];
                const card = cards.find(c => !c.textContent.includes('Solved')) || cards[0];
                if (!card) return 'no card';
                const label = card.textContent.slice(0, 40);
                card.click();
                return 'clicked: ' + label;
              })()""")
            print(f"  card {clicked}")
            await asyncio.sleep(3)
            state = await evaljs(ws, "!!document.querySelector('[role=dialog]')")
            print(f"  dialog open: {state}")
            await shot(ws, "challenge-dialog", selector="[role=dialog]", pad=10)
            await evaljs(ws, "document.activeElement && document.activeElement.blur(), true")
            await cdp(ws, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape"})
            await cdp(ws, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape"})

            # ── scoreboard ──
            await goto(ws, f"{BASE}/scoreboard", settle=3)
            await shot(ws, "scoreboard", selector="#main-content")

            # ── support ──
            await goto(ws, f"{BASE}/support", settle=3)
            await shot(ws, "support", selector="#main-content")

        return 0
    finally:
        proc.send_signal(signal.SIGTERM)
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
        if PROFILE.exists(): shutil.rmtree(PROFILE, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
