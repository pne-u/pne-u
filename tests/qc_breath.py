"""python tests/qc_breath.py [card.svg] : QC of the banner breath animation (SMIL).
 - reads the animation values and prints t / left length / right length / dot opacity, asserting the spec's invariants
 - renders deterministic frames with svg.setCurrentTime(t) (0..8s, 0.25s steps) into qc/breath-sheet.png
 - pixel check on the zero-length frames, title legibility in every frame, reduced-motion fallback
 - one real-time check through an <img> tag (two screenshots 1.5s apart)
value_at() / banner_anims() are also used by tests/test_card.py."""
import base64, io, json, pathlib, re, subprocess, sys, tempfile, time, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
NS = "{http://www.w3.org/2000/svg}"
ROOT = pathlib.Path(__file__).resolve().parents[1]
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def banner_anims(svg_text):
    """{'left'|'right': {'len': animate, 'off': .., 'opacity': .., 'cap': ..}, 'dot': animate} read from the SVG."""
    root = ET.fromstring(svg_text)
    out = {}
    bright = [e for e in root.iter(NS + "path") if e.get("class") == "bright"]
    for side, e in zip(("left", "right"), bright):
        a = {x.get("attributeName"): x for x in e.findall(NS + "animate")}
        out[side] = {"len": a["stroke-dasharray"], "off": a["stroke-dashoffset"], "opacity": a["opacity"], "cap": a["stroke-linecap"]}
    dot = [e for e in root.iter(NS + "circle") if e.get("class") == "dot"][0]
    out["dot"] = [x for x in dot.findall(NS + "animate") if x.get("attributeName") == "opacity"][0]
    out["dscale"] = [x for x in dot.findall(NS + "animateTransform")][0]
    out["loop"] = float(dot.find(NS + "animate").get("dur").rstrip("s"))
    return out


def value_at(anim, t, loop):
    """Value of an <animate> at loop time t. Numbers (first token of a list) are linearly interpolated; discrete values step."""
    times = [float(x) for x in anim.get("keyTimes").split(";")]
    vals = anim.get("values").split(";")
    f = 1.0 if t >= loop else (t % loop) / loop
    discrete = anim.get("calcMode") == "discrete"
    i = max(k for k, kt in enumerate(times) if kt <= f + 1e-12)

    def num(v):
        try:
            return float(v.split()[0])
        except ValueError:
            return v
    if discrete or i == len(times) - 1:
        return num(vals[i])
    a, b = num(vals[i]), num(vals[i + 1])
    w = (f - times[i]) / (times[i + 1] - times[i])
    return a + (b - a) * w


def seg_len(an, side, t):
    return value_at(an[side]["len"], t, an["loop"])


class Browser:
    def __init__(self, port, size=(830, 400)):
        from websockets.sync.client import connect
        self.proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", f"--window-size={size[0]},{size[1]}",
                                      "--user-data-dir=" + tempfile.mkdtemp(), "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except Exception:
                time.sleep(0.2)
        self.ws = connect([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], max_size=2**26)
        self.n = 0
        self.call("Page.enable")
        self.call("Emulation.setDeviceMetricsOverride", width=size[0], height=size[1], deviceScaleFactor=1, mobile=False)   # headless Edge clamps narrow windows to ~500px

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                return m.get("result")

    def open(self, path):
        self.call("Page.navigate", url=pathlib.Path(path).resolve().as_uri())
        while self.call("Runtime.evaluate", expression="document.readyState")["result"]["value"] != "complete":
            time.sleep(0.02)

    def js(self, expr):
        return self.call("Runtime.evaluate", expression=expr)["result"].get("value")

    def shot(self, clip=(0, 0, 830, 130)):
        from PIL import Image
        r = self.call("Page.captureScreenshot", format="png", clip={"x": clip[0], "y": clip[1], "width": clip[2], "height": clip[3], "scale": 1})
        return Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGB")

    def close(self):
        self.proc.terminate()


def main(svg_path):
    import numpy as np
    from PIL import Image, ImageDraw
    svg = pathlib.Path(svg_path).read_text(encoding="utf-8")
    an = banner_anims(svg)
    loop = an["loop"]
    bad = []
    # ---- b. table from the animation values
    import build_card as bc
    meas = {"inhale": bc.LEFT_E - bc.LEFT_S, "hold": bc.RIGHT_S - bc.LEFT_E, "exhale": bc.RIGHT_E - bc.RIGHT_S, "total": loop}
    print("measured from the SVG:", meas)
    for k, v in zip(("inhale", "hold", "exhale", "total"), (4.0, 2.0, 6.0, 12.0)):
        if abs(meas[k] - v) > 0.05:
            bad.append(f"{k} {meas[k]} != {v}")
    print(f"{'t':>5} {'left len':>9} {'right len':>10} {'dot opacity':>12} {'dot scale':>10}")
    for k in range(49):
        t = k * 0.25
        print(f"{t:5.2f} {seg_len(an, 'left', t):9.4f} {seg_len(an, 'right', t):10.4f} {value_at(an['dot'], t, loop):12.4f} {value_at(an['dscale'], t, loop):10.4f}")
    dense = [i / 100 for i in range(0, 1201)]
    for t in dense:
        if 4.0 <= t <= 6.0 and (seg_len(an, "left", t) or seg_len(an, "right", t) or abs(value_at(an["dot"], t, loop) - value_at(an["dot"], 4.0, loop)) > 1e-9 or abs(value_at(an["dscale"], t, loop) - value_at(an["dscale"], 4.0, loop)) > 1e-9):
            bad.append(f"hold not still at {t}")
            break
    for side, (s, e) in (("left", (bc.LEFT_S, bc.LEFT_E)), ("right", (bc.RIGHT_S, bc.RIGHT_E))):
        L = [seg_len(an, side, t) for t in dense]
        if min(L) < 0:
            bad.append(f"{side} negative length")
        inside = [seg_len(an, side, t) for t in dense if s < t < e]
        outside = [seg_len(an, side, t) for t in dense if t <= s or t >= e]
        peak = max(inside)
        print(f"{side}: peak length {peak:.4f} at t={dense[L.index(max(L))]:.2f}; max outside its phase {max(outside):.6f}; length at phase end {seg_len(an, side, e):.6f}")
        if not 0.40 <= peak <= 0.42 or max(outside) > 1e-9 or abs(seg_len(an, side, e)) > 1e-9:
            bad.append(f"{side} length envelope")
        for t in dense:
            op = value_at(an[side]["opacity"], t, loop)
            if (t < s or t > e) and op != 0:
                bad.append(f"{side} opacity {op} outside phase at {t}")
                break
            if value_at(an[side]["cap"], t, loop) == "round" and seg_len(an, side, t) <= 0:
                bad.append(f"{side} round cap with zero length at {t}")
                break
    dots = [value_at(an["dot"], t, loop) for t in dense]
    pk = dense[dots.index(max(dots))]
    print(f"dot opacity: rest {dots[0]:.2f}, first reaches its peak {max(dots):.2f} at t={pk:.2f}; at 3.7s {value_at(an['dot'], 3.7, loop):.2f}; at 5.0s {value_at(an['dot'], 5.0, loop):.2f}; at 2.4s {value_at(an['dot'], 2.4, loop):.2f}")
    if abs(pk - 4.0) > 0.011 or abs(value_at(an["dot"], 12.0, loop) - dots[0]) > 1e-6 or abs(value_at(an["dot"], 2.5, loop) - dots[0]) > 1e-6:
        bad.append("dot opacity timeline")
    # ---- a. deterministic frames
    root = ET.fromstring(svg)
    bright = [e for e in root.iter(NS + "path") if e.get("class") == "bright"]
    nums = lambda d: [float(v) for v in re.findall(r"-?\d+\.?\d*", d)]
    lt, rt = nums(bright[0].get("d"))[:2], nums(bright[1].get("d"))[-2:]
    br = Browser(9343)
    frames = {}
    try:
        br.open(svg_path)
        for t in [k * 0.25 for k in range(49)] + [3.9, 5.9, 11.9]:   # the grid, plus the phase boundaries for the pixel check
            br.js(f"(()=>{{const s=document.documentElement; s.pauseAnimations(); s.setCurrentTime({t});}})()")
            frames[t] = br.shot()
        br.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        br.js("document.documentElement.setCurrentTime(1.0)")
        red = br.js("JSON.stringify({bright:getComputedStyle(document.querySelector('.bright')).display, glow:getComputedStyle(document.querySelector('.glow')).display, dotw:getComputedStyle(document.querySelector('.dotw')).display, dots:getComputedStyle(document.querySelector('.dots')).display, base:getComputedStyle(document.querySelector('.base')).opacity})")
        (ROOT / "qc").mkdir(exist_ok=True)
        br.shot().save(ROOT / "qc" / "breath-reduced.png")
    finally:
        br.close()
    print("reduced-motion computed styles:", red)
    r = json.loads(red)
    if not (r["bright"] == "none" and r["glow"] == "none" and r["dotw"] == "none" and r["dots"] != "none" and abs(float(r["base"]) - 0.7) < 1e-6):
        bad.append("reduced-motion fallback")
    ST = (0, 1, 2, 3, 3.9, 4, 5, 5.9, 6, 7.5, 9, 11, 11.9)
    sheet = Image.new("RGB", (1245, 5 * 71), (60, 60, 60))
    for k, t in enumerate(ST):
        im = frames[float(t)].resize((415, 65), Image.LANCZOS)
        ImageDraw.Draw(im).text((4, 2), f"{t:.2f}s", fill=(255, 220, 120))
        sheet.paste(im, ((k % 3) * 415, (k // 3) * 71))
    sheet.save(ROOT / "qc" / "tempo-sheet.png")
    ref = np.asarray(frames[11.9]).astype(int).mean(axis=2)
    mask = np.zeros(ref.shape, bool)
    mask[30:100, 330:500] = True
    mask &= ref > 200
    kept = {t: float((np.asarray(im).astype(int).mean(axis=2)[mask] > 150).mean()) for t, im in frames.items()}
    print(f"title ink kept (share of title pixels still bright): min {min(kept.values()):.1%} over {len(kept)} frames")
    if min(kept.values()) < 0.97:
        bad.append("title legibility")
    # ---- c. pixel check on zero-length frames
    base = np.asarray(frames[11.9]).astype(int)
    print("stray bright pixels (white increase vs the rest frame, 9x9 around path start/end points):")
    for t in (0.0, 4.0, 5.0, 6.0, 11.9):
        a = np.asarray(frames[t]).astype(int)
        row = []
        for name, (x, y) in (("left start", lt), ("right end", rt)):
            x, y = int(round(x)), int(round(y))
            win = lambda arr: arr[y - 4:y + 5, x - 4:x + 5].min(axis=2)
            inc = int(((win(a) - win(base)) > 40).sum())
            row.append(f"{name} {inc}")
            if inc:
                bad.append(f"stray pixels at {name}, t={t}")
        print(f"  t={t:4}s: " + ", ".join(row))
    # ---- d. real time through an <img>
    page = ROOT / "qc" / "breath-img.html"
    page.write_text('<!doctype html><meta charset=utf-8><body style="margin:0;background:#0d1117"><img src="card-live.svg" width="830" style="display:block">', encoding="utf-8")
    (ROOT / "qc" / "card-live.svg").write_text(svg, encoding="utf-8")
    br = Browser(9344)
    try:
        br.open(page)
        t0 = time.time()
        shots = {}
        for name, at in (("i1", 1.0), ("i2", 2.0), ("h1", 4.5), ("h2", 5.5)):
            time.sleep(max(0, at - (time.time() - t0)))
            shots[name] = np.asarray(br.shot()).astype(int)
    finally:
        br.close()
    d = lambda x, y: int((np.abs(shots[x] - shots[y]).max(axis=2) > 30).sum())
    print(f"real time through <img>: inhale 1s->2s {d('i1', 'i2')} px changed; hold 4.5s->5.5s {d('h1', 'h2')} px changed")
    if d("i1", "i2") < 100:
        bad.append("no real-time change in the inhale")
    if d("h1", "h2") > 0:
        bad.append("banner not still during the hold")
    print("PASS" if not bad else "FAIL: " + "; ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "assets" / "card.svg")))
