"""python tests/qc_card.py [card.svg] : XML, size, forbidden content, font sizes and contrast of the finished SVG.
Exits 1 if any rule fails. Rules: every font-size >= 16, every text colour >= 7:1 on the card background,
no scripts, no external references, no '//' labels, no small all-caps labels, no opacity on text."""
import pathlib, re, sys
import xml.etree.ElementTree as ET

MIN_SIZE, MIN_CONTRAST, MAX_BYTES = 16, 7.0, 150_000
NS = "{http://www.w3.org/2000/svg}"


def lum(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check(path):
    raw = pathlib.Path(path).read_bytes()
    fails, rows = [], []
    root = ET.fromstring(raw)  # raises if not well-formed
    if len(raw) >= MAX_BYTES:
        fails.append(f"size {len(raw):,} >= {MAX_BYTES:,}")
    src = raw.decode("utf-8")
    if "<script" in src.lower():
        fails.append("contains <script")
    for m in re.findall(r'(?:href|src)\s*=\s*"([^"]*)"|url\(\s*([^)]*)\)', src):
        ref = (m[0] or m[1]).strip("'\" ")
        if ref and not ref.startswith(("#", "data:")):
            fails.append(f"external reference: {ref[:60]}")
    if "@import" in src:
        fails.append("@import")
    bg = next(e.get("fill") for e in root.iter(NS + "rect") if e.get("fill", "").startswith("#"))

    def walk(el, size, fill):
        size, fill = el.get("font-size", size), el.get("fill", fill)
        if el.tag in (NS + "text", NS + "tspan"):
            if "opacity" in el.attrib or "opacity" in el.get("style", ""):
                fails.append(f"opacity on text {el.text!r}")
            t = (el.text or "").strip()
            if t:
                rows.append((t, float(size), fill, contrast(fill, bg)))
                if "//" in t:
                    fails.append(f"'//' label: {t!r}")
                if t.isupper() and len(t) > 3 and float(size) < 40:
                    fails.append(f"small all-caps label: {t!r}")
        for c in el:
            walk(c, size, fill)

    walk(root, None, None)
    for t, size, fill, c in rows:
        if size < MIN_SIZE:
            fails.append(f"font-size {size} < {MIN_SIZE}: {t!r}")
        if c < MIN_CONTRAST:
            fails.append(f"contrast {c:.2f} < {MIN_CONTRAST}: {t!r}")
    return raw, bg, rows, fails


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parents[1] / "assets" / "card.svg")
    raw, bg, rows, fails = check(path)
    print(f"well-formed XML, {len(raw):,} bytes, background {bg}")
    print(f"min font-size: {min(r[1] for r in rows):g}px over {len(rows)} text nodes")
    seen = {}
    for t, size, fill, c in rows:
        seen.setdefault((fill, round(c, 2)), []).append(size)
    print("fill      contrast  min-size  count")
    for (fill, c), sizes in sorted(seen.items(), key=lambda kv: kv[0][1]):
        print(f"{fill:9} {c:6.2f}:1  {min(sizes):6g}px  {len(sizes)}")
    print("FAIL" if fails else "PASS", *fails, sep="\n  " if fails else "")
    sys.exit(1 if fails else 0)
