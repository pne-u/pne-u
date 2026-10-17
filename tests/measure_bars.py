"""python tests/measure_bars.py [card.svg] : render the card to a PNG (headless Edge, 2x) and measure, on the mid-line of every
bar, the fill length against the track length. Prints a table and exits 1 if any fill is off by more than 1px from its true percent."""
import pathlib, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from PIL import Image

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SCALE, TOL = 2, 1.0


def render(svg_path, out_png):
    root = ET.parse(svg_path).getroot()
    w, h = int(float(root.get("width"))), int(float(root.get("height")))
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={SCALE}",
                    f"--window-size={w},{h + 200}", f"--screenshot={out_png}", pathlib.Path(svg_path).resolve().as_uri()],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    return root


def run_length(row, lo, hi, thr):
    xs = [x for x in range(lo, hi) if sum(row[x][:3]) / 3 > thr]
    return (xs[-1] - xs[0] + 1) / SCALE if xs else 0.0


def main(svg):
    png = pathlib.Path(tempfile.mkdtemp()) / "card.png"
    root = render(svg, png)
    im = Image.open(png).convert("RGB")
    px = im.load()
    NS = "{http://www.w3.org/2000/svg}"
    bad, rows = [], []
    for e in root.iter():
        if e.get("class") != "fil":
            continue
        t0, t1, yc, pct = (float(e.get(k)) for k in ("data-t0", "data-t1", "data-yc", "data-pct"))
        y = int(round(yc * SCALE))
        row = [px[x, y] for x in range(im.width)]
        lo, hi = int((t0 - 4) * SCALE), int((t1 + 4) * SCALE)
        track = run_length(row, lo, hi, 24)           # track and fill are both brighter than the page background
        fill = run_length(row, lo, hi, 60)            # only the fill clears this brightness
        want = (t1 - t0) * min(pct, 100) / 100
        rows.append((e.get("data-label"), pct, t1 - t0, track, want, fill, fill - want))
        if abs(fill - want) > TOL or abs(track - (t1 - t0)) > TOL:
            bad.append(rows[-1])
    print(f"{'bar':12} {'true %':>8} {'track px':>9} {'measured':>9} {'want px':>8} {'fill px':>8} {'diff':>6}")
    for r in rows:
        print(f"{r[0]:12} {r[1]:8.2f} {r[2]:9.1f} {r[3]:9.1f} {r[4]:8.2f} {r[5]:8.1f} {r[6]:+6.2f}")
    print("PASS" if not bad else f"FAIL: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parents[1] / "assets" / "card.svg")))
