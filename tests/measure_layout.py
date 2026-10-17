"""python tests/measure_layout.py [card.svg] : render the card in headless Edge and measure real bounding boxes of the bordered panels
(<g id="sec-*"> with a <rect class="panel">). Checks: card height <= MAX_H (fits one screen), panels never overlap and are 6-14px apart,
every panel's content sits inside its border with >= 8px padding, no two text boxes inside a panel overlap, nothing leaves the
canvas, and the banner stays clear of the first row. Exits 1 on failure."""
import json, pathlib, subprocess, sys, tempfile, time, urllib.request
from websockets.sync.client import connect

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
MAX_H, MIN_GAP, MAX_GAP, MIN_PAD = 760, 6, 14, 8
JS = """JSON.stringify((() => {
  const out = {panels: {}, canvas: [0, 0, +document.documentElement.getAttribute('width'), +document.documentElement.getAttribute('height')], banner: null};
  const box = e => {const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]};
  for (const g of document.querySelectorAll('g[id^=sec-]')) {
    const name = g.id.slice(4), rect = g.querySelector(':scope > rect.panel');
    const kids = [...g.children].filter(c => c !== rect && typeof c.getBBox === 'function');
    const u = kids.map(box);
    const content = u.length ? [Math.min(...u.map(b => b[0])), Math.min(...u.map(b => b[1])), Math.max(...u.map(b => b[2])), Math.max(...u.map(b => b[3]))] : null;
    const texts = [...g.querySelectorAll('text')].filter(t => !t.closest('title')).map(t => [t.textContent, ...box(t)]);
    if (rect) out.panels[name] = {panel: box(rect), content, texts}; else if (name === 'banner') out.banner = content;
  }
  return out;
})())"""


def measure(svg):
    port = 9338
    proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", "--window-size=880,1100",
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


def gap(a, b):
    dx, dy = max(a[0] - b[2], b[0] - a[2]), max(a[1] - b[3], b[1] - a[3])
    return max(dx, dy) if (dx < 0 or dy < 0) else None   # None: only touching at corners, not neighbours


def main(svg):
    data = measure(svg)
    P, canvas, bad = data["panels"], data["canvas"], []
    print(f"card height {canvas[3]:.0f}px (limit {MAX_H}); panels: {', '.join(P)}")
    if canvas[3] > MAX_H:
        bad.append(f"height {canvas[3]} > {MAX_H}")
    names = sorted(P)
    gaps = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            g = gap(P[a]["panel"], P[b]["panel"])
            if g is not None and g < 40:
                gaps.append((g, a, b))
                if g < MIN_GAP or g > MAX_GAP:
                    bad.append(f"panel gap {a}-{b} {g:.1f} outside {MIN_GAP}-{MAX_GAP}")
    print("neighbouring panel gaps (px):", sorted({round(g, 1) for g, _, _ in gaps}))
    print(f"{'panel':9} {'padding L/T/R/B (px)':>26}  text overlaps")
    for name in names:
        p, c = P[name]["panel"], P[name]["content"]
        pad = (c[0] - p[0], c[1] - p[1], p[2] - c[2], p[3] - c[3])
        texts = P[name]["texts"]
        ov = [(a[0], b[0]) for i, a in enumerate(texts) for b in texts[i + 1:]
              if a[1] < b[3] and b[1] < a[3] and a[2] + 0.22 * (a[4] - a[2]) < b[4] - 0.22 * (b[4] - b[2]) and b[2] + 0.22 * (b[4] - b[2]) < a[4] - 0.22 * (a[4] - a[2])]   # boxes shrunk 22% top and bottom: font ascent/descent slack
        print(f"{name:9} {pad[0]:6.1f} {pad[1]:6.1f} {pad[2]:6.1f} {pad[3]:6.1f}   {ov or 'none'}")
        if min(pad) < MIN_PAD:
            bad.append(f"{name} padding {min(pad):.1f} < {MIN_PAD}")
        if ov:
            bad.append(f"{name} text overlap {ov}")
    tops = min(P[n]["panel"][1] for n in names)
    clear = tops - data["banner"][3]
    print(f"banner content bottom {data['banner'][3]:.1f}, first panel top {tops:.1f}, clearance {clear:.1f}px")
    if clear < 0:
        bad.append("banner overlaps first row")
    out = [n for n in names if P[n]["panel"][0] < canvas[0] or P[n]["panel"][2] > canvas[2] or P[n]["panel"][3] > canvas[3]]
    print("panels leaving the canvas:", out or "none")
    bad += [f"{n} leaves canvas" for n in out]
    print("PASS" if not bad else "FAIL: " + "; ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parents[1] / "assets" / "card.svg")))
