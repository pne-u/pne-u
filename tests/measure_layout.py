"""python tests/measure_layout.py [card.svg] : render the card in headless Edge and measure the real bounding boxes of the section groups
(<g id="sec-*">). Checks: >=40px between every pair of groups, >=48px between rows, >=56px column gutter, and that the Activity
"total" stays inside its column (right-aligned to the column edge) at least 40px from the Streak group. Exits 1 on failure."""
import json, pathlib, subprocess, sys, tempfile, time, urllib.request
from websockets.sync.client import connect

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ROWS = [["banner"], ["tokens"], ["daily", "tod", "weekday"], ["activity", "streak"], ["langs", "stack"], ["footer"]]
COLUMNS = [("daily", "tod"), ("daily", "weekday"), ("activity", "streak"), ("langs", "stack")]
MIN_PAIR, MIN_ROW, MIN_GUTTER, MIN_TOTAL = 40, 48, 56, 40
COLUMN_RIGHT = 40 + 520  # M + LEFT_W: right edge of the left column


def boxes(svg):
    port = 9335
    proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", "--window-size=880,1500",
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
        js = """JSON.stringify({groups: Object.fromEntries([...document.querySelectorAll('g[id^=sec-]')].map(g => {const b = g.getBBox(); return [g.id.slice(4), [b.x, b.y, b.x + b.width, b.y + b.height]]})),
                 total: (() => {const t = [...document.querySelectorAll('#sec-activity text')].find(t => t.textContent.startsWith('total')); const b = t.getBBox(); return [b.x, b.y, b.x + b.width, b.y + b.height]})()})"""
        return json.loads(call("Runtime.evaluate", expression=js)["result"]["value"])
    finally:
        proc.terminate()


def gap(a, b):
    dx, dy = max(a[0] - b[2], b[0] - a[2]), max(a[1] - b[3], b[1] - a[3])
    return max(dx, dy) if (dx < 0 or dy < 0) else (dx * dx + dy * dy) ** 0.5


def union(bs):
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


def main(svg):
    data = boxes(svg)
    g, total = data["groups"], data["total"]
    bad = []
    print("pairs of section groups (gap in px, only pairs under 120 shown):")
    names = sorted(g)
    pair_min = 1e9
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = gap(g[a], g[b])
            pair_min = min(pair_min, v)
            if v < 120:
                print(f"  {a:9} - {b:9} {v:6.1f}")
            if v < MIN_PAIR:
                bad.append(f"{a}-{b} {v:.1f} < {MIN_PAIR}")
    print(f"min gap between any two groups: {pair_min:.1f}px (need {MIN_PAIR})")
    rows = [union([g[n] for n in r if n in g]) for r in ROWS]
    rgaps = [rows[i + 1][1] - rows[i][3] for i in range(len(rows) - 1)]
    print("row-to-row gaps:", [round(v, 1) for v in rgaps], f"(need {MIN_ROW})")
    bad += [f"row gap {v:.1f} < {MIN_ROW}" for v in rgaps if v < MIN_ROW]
    gut = {f"{a}|{b}": g[b][0] - g[a][2] for a, b in COLUMNS if a in g and b in g}
    print("column gutters:", {k: round(v, 1) for k, v in gut.items()}, f"(need {MIN_GUTTER})")
    bad += [f"gutter {k} {v:.1f} < {MIN_GUTTER}" for k, v in gut.items() if v < MIN_GUTTER]
    inside = g["activity"][0] <= total[0] and total[2] <= g["activity"][2] + 0.5
    edge = abs(total[2] - COLUMN_RIGHT)
    to_streak = g["streak"][0] - total[2]
    print(f"total text box right edge {total[2]:.1f} (column edge {COLUMN_RIGHT}, diff {edge:.1f}); inside Activity group: {inside}; to Streak: {to_streak:.1f}px (need {MIN_TOTAL})")
    if not inside or edge > 2 or to_streak < MIN_TOTAL:
        bad.append("total text placement")
    print("PASS" if not bad else "FAIL: " + "; ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parents[1] / "assets" / "card.svg")))
