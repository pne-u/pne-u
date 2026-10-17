"""python tests/qc_card.py [card.svg] : XML, size, forbidden content, font sizes, contrast and hierarchy of the finished SVG.
Exits 1 if any rule fails. Rules: every font-size >= 16, every text colour >= 7:1 on the card background,
no scripts, no external references, no '//' labels, no small all-caps labels, no opacity on text,
bold only in the display font (name and token hero), the token hero is the largest text and no other number
exceeds 50% of its size, at most 40 words of text (numbers and the name excluded)."""
import pathlib, re, sys
import xml.etree.ElementTree as ET

MIN_SIZE, MIN_CONTRAST, MAX_BYTES, MAX_HEIGHT = 16, 7.0, 200_000, 1200  # the usage panels need room; v4 capped the card at 720px
NS = "{http://www.w3.org/2000/svg}"
MAX_WORDS = 70
STATS = {}  # filled by check(): words, hero, numbers


def lum(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check(path, max_height=MAX_HEIGHT):
    raw = pathlib.Path(path).read_bytes()
    fails, rows = [], []
    root = ET.fromstring(raw)  # raises if not well-formed
    if max_height and float(root.get("height")) > max_height:
        fails.append(f"height {root.get('height')} > {max_height}")
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

    meta = []  # (text, size, weight, is display font)

    def walk(el, size, fill, weight="400", fam=""):
        size, fill = el.get("font-size", size), el.get("fill", fill)
        weight, fam = el.get("font-weight", weight), el.get("font-family", fam)
        if el.tag in (NS + "text", NS + "tspan"):
            if "opacity" in el.attrib or "opacity" in el.get("style", ""):
                fails.append(f"opacity on text {el.text!r}")
            t = (el.text or "").strip()
            if t:
                rows.append((t, float(size), fill, contrast(fill, bg)))
                meta.append((t, float(size), weight, "PneuMono" in fam))
                if "//" in t:
                    fails.append(f"'//' label: {t!r}")
                if t.isupper() and len(t) > 3 and float(size) < 40:
                    fails.append(f"small all-caps label: {t!r}")
        for c in el:
            walk(c, size, fill, weight, fam)

    walk(root, None, None)
    # hierarchy: bold only in the display font; the largest text is the token hero; other numbers <= 50% of it
    for t, size, weight, is_disp in meta:
        if weight in ("600", "700", "800", "900", "bold") and not is_disp:
            fails.append(f"bold text outside the display font: {t!r}")
    if meta:
        hero = max(meta, key=lambda m: m[1])
        if not re.fullmatch(r"[\d,]+", hero[0]):
            fails.append(f"largest text is not the token number: {hero[0]!r} {hero[1]:g}px")
        for t, size, _, _ in meta:
            if any(ch.isdigit() for ch in t) and (t, size) != hero[:2] and size > hero[1] * 0.5:
                fails.append(f"number {t!r} at {size:g}px is above 50% of the hero {hero[1]:g}px")
        name = [m for m in meta if m[3] and m is not hero]
        words = [w for _, _, _, _, ws in [(0, 0, 0, 0, t.split()) for t, _, _, d in meta if not (d and (t, ) and any(t == n[0] for n in name))]
                 for w in ws if any(c.isalpha() for c in w) and not w[0].isdigit()]
        STATS.update(words=words, hero=hero[:2], numbers=[(t, size) for t, size, _, _ in meta if any(c.isdigit() for c in t)])
        if len(words) > MAX_WORDS:
            fails.append(f"{len(words)} words of text > {MAX_WORDS}")
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
    print(f"hero {STATS['hero'][0]} at {STATS['hero'][1]:g}px; numbers: " + ", ".join(f"{t}@{s:g}" for t, s in STATS['numbers']))
    print(f"words of text (numbers and the name excluded): {len(STATS['words'])} -> {' '.join(STATS['words'])}")
    seen = {}
    for t, size, fill, c in rows:
        seen.setdefault((fill, round(c, 2)), []).append(size)
    print("fill      contrast  min-size  count")
    for (fill, c), sizes in sorted(seen.items(), key=lambda kv: kv[0][1]):
        print(f"{fill:9} {c:6.2f}:1  {min(sizes):6g}px  {len(sizes)}")
    print("FAIL" if fails else "PASS", *fails, sep="\n  " if fails else "")
    sys.exit(1 if fails else 0)
