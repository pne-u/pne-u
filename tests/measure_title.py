"""python tests/measure_title.py [card.svg] : render the card in headless Edge and measure the real bounding boxes of the title letters (P, N, E, U)
and the red dot. Axis = (right edge of N + left edge of E) / 2. Checks: axis == card centre, dot centre on the axis, dot y == middle of the
capital letters, equal space on both sides of the dot, tagline centred on the axis, header clear of the first card. Exits 1 on failure."""
import json, pathlib, subprocess, sys, tempfile, time, urllib.request
from websockets.sync.client import connect

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
JS = """JSON.stringify((() => {
  document.documentElement.pauseAnimations(); document.documentElement.setCurrentTime(0);   // dot at rest scale
  const r = e => {const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]};
  const letters = [...document.querySelectorAll('#title path')].map(e => [e.id, ...r(e)]);
  const dot = r(document.querySelector('circle.dot'));
  const tag = [...document.querySelectorAll('#sec-banner text')].find(t => t.textContent.includes('systems'));
  const panel = document.querySelector('rect.panel');
  const banner = [...document.querySelectorAll('#sec-banner > *')].map(r);
  return {letters, dot, width: +document.documentElement.getAttribute('width'), tag: r(tag), panelTop: r(panel)[1], bannerBottom: Math.max(...banner.map(b => b[3]))};
})())"""


def measure(svg):
    port = 9340
    proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", "--window-size=830,400",
                             "--user-data-dir=" + tempfile.mkdtemp(), "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except Exception:
                time.sleep(0.2)
        ws = connect([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], max_size=2**26)
        n = [0]

        def call(method, **params):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == n[0]:
                    return m.get("result")
        call("Page.enable")
        call("Page.navigate", url=pathlib.Path(svg).resolve().as_uri())
        time.sleep(1.5)
        return json.loads(call("Runtime.evaluate", expression=JS)["result"]["value"])
    finally:
        proc.terminate()


def main(svg):
    m = measure(svg)
    L = {e[0].split("-")[1]: e[1:] for e in m["letters"]}
    N, E, P = L["N"], L["E"], L["P"]
    axis = (N[2] + E[0]) / 2
    dot = m["dot"]
    dcx, dcy, r = (dot[0] + dot[2]) / 2, (dot[1] + dot[3]) / 2, (dot[2] - dot[0]) / 2
    cap_mid = (P[1] + P[3]) / 2
    left, right = dot[0] - N[2], E[0] - dot[2]
    tag_c = (m["tag"][0] + m["tag"][2]) / 2
    print("letters (rendered): " + ", ".join(f"{k} x {v[0]:.1f}..{v[2]:.1f}" for k, v in L.items()))
    print(f"axis = (N right {N[2]:.2f} + E left {E[0]:.2f}) / 2 = {axis:.2f}; card centre = {m['width'] / 2:.2f}")
    print(f"red dot centre ({dcx:.2f}, {dcy:.2f}) r={r:.1f}; middle of capital letters y = {cap_mid:.2f}")
    print(f"space left of dot (N edge to dot) = {left:.2f}px; right of dot (dot to E edge) = {right:.2f}px")
    print(f"tagline centre x = {tag_c:.2f}, top {m['tag'][1]:.1f} (title bottom {P[3]:.1f}); header bottom {m['bannerBottom']:.1f} vs first card top {m['panelTop']:.1f}")
    bad = []
    if abs(axis - m["width"] / 2) > 0.6:
        bad.append("axis not at card centre")
    if abs(dcx - axis) > 0.6:
        bad.append("dot not on axis")
    if abs(dcy - cap_mid) > 0.8:
        bad.append("dot not at cap-height middle")
    if abs(left - right) > 0.8:
        bad.append("unequal space around dot")
    if abs(tag_c - axis) > 1.5 or m["tag"][1] < P[3]:
        bad.append("tagline not centred under the title")
    if m["bannerBottom"] > m["panelTop"] - 6:
        bad.append("header too close to the first card")
    print("PASS" if not bad else "FAIL: " + "; ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parents[1] / "assets" / "card.svg")))
