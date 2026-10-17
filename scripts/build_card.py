#!/usr/bin/env python3
"""Draws assets/card.svg ("breath" design) from data/*.json, the GitHub contribution calendar and language bytes.

  python scripts/build_card.py                 online: gh api (GH_TOKEN or a logged-in gh)
  python scripts/build_card.py --offline DIR   DIR/contributions.json + DIR/languages.json, no network
  python scripts/build_card.py --fetch-icons   cache simple-icons paths into data/icons.json

Stdlib only. The SVG has no scripts, no external requests, no web fonts: a monospace system stack and
inlined icon paths, one OFL display font subset (data/display-font.b64). Own #0A0A0A background, so it reads the
same in light and dark mode. Motion is CSS inside the SVG and is off under prefers-reduced-motion.
"""
import argparse, datetime, json, math, pathlib, re, subprocess, urllib.error, urllib.request, zlib
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parents[1]
ICON_URL = "https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/{}.svg"

# Breath timeline: seconds on one loop. Every keyframe time in the banner is derived from these.
INHALE, HOLD, EXHALE = 4.0, 2.0, 6.0
LOOP = INHALE + HOLD + EXHALE
LEFT_S, LEFT_E = 0.0, INHALE           # left line: grows from the left spiral's centre, collapses into the dot
RIGHT_S, RIGHT_E = INHALE + HOLD, LOOP # right line: grows out of the dot, collapses at the right spiral's centre
DOT_WARM = INHALE - 1.5                # dot warms over the last 1.5s of the inhale, holds the peak through HOLD, eases to rest across EXHALE
DOT_REST_OPACITY = 0.55
STEPS = 20                             # linear keyframes per phase


# ---------------------------------------------------------------- data

def gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", timeout=120,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {done.stderr.strip()[:200]}")
    return done.stdout


def calendars_online(login, now):
    q = f'{{user(login:"{login}"){{contributionsCollection{{contributionYears}}}}}}'
    years = json.loads(gh("api", "graphql", "-f", f"query={q}"))["data"]["user"]["contributionsCollection"]["contributionYears"]
    cal = "contributionCalendar{weeks{contributionDays{date contributionCount}}}"
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = " ".join(f'y{y}:contributionsCollection(from:"{y}-01-01T00:00:00Z",to:"{min(f"{y}-12-31T23:59:59Z", end)}"){{{cal}}}'
                     for y in years)
    data = json.loads(gh("api", "graphql", "-f", f'query={{user(login:"{login}"){{{parts}}}}}'))
    return [v["contributionCalendar"] for v in data["data"]["user"].values()]


def languages_online(login):
    names = gh("api", "--paginate", f"users/{login}/repos?per_page=100&type=owner",
               "--jq", ".[] | select(.fork|not) | .name").split()
    total = {}
    for n in names:
        for lang, b in json.loads(gh("api", f"repos/{login}/{n}/languages")).items():
            total[lang] = total.get(lang, 0) + b
    return total


def flatten(calendars):
    days = {}
    for c in calendars:
        for w in c["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
    return days


def streaks(days, today):
    """(current, best). Current counts back from today, or from yesterday while today is still 0."""
    best = run = 0
    prev = None
    for d in sorted(days):
        dt = datetime.date.fromisoformat(d)
        if days[d] <= 0:
            run = 0
        elif prev and (dt - prev).days == 1 and days[prev.isoformat()] > 0:
            run += 1
        else:
            run = 1
        best = max(best, run)
        prev = dt
    cur, d = 0, today if days.get(today.isoformat(), 0) > 0 else today - datetime.timedelta(days=1)
    while days.get(d.isoformat(), 0) > 0:
        cur, d = cur + 1, d - datetime.timedelta(days=1)
    return cur, best


def ma7(days, dates):
    """7-day moving average ending on each date; days the calendar lacks are skipped (partial window)."""
    out = []
    for d in dates:
        win = [days[str(d - datetime.timedelta(days=k))] for k in range(7) if str(d - datetime.timedelta(days=k)) in days]
        out.append(sum(win) / len(win) if win else 0.0)
    return out


def et_now(now):
    """now (UTC) shifted to US Eastern wall-clock time. Own DST rule so no tz database is needed."""
    def nth_sunday(year, month, nth, hour):
        d = datetime.datetime(year, month, 1, hour, tzinfo=datetime.timezone.utc)
        return d + datetime.timedelta(days=(6 - d.weekday()) % 7 + 7 * (nth - 1))
    dst = nth_sunday(now.year, 3, 2, 7) <= now < nth_sunday(now.year, 11, 1, 6)
    return now + datetime.timedelta(hours=-4 if dst else -5)


def read(name, default=None):
    p = ROOT / "data" / name
    if not p.exists() and default is not None:
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def gather(offline=None, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    prof = read("profile.json")
    if offline:
        off = pathlib.Path(offline)
        cals = json.loads((off / "contributions.json").read_text(encoding="utf-8"))
        langs = json.loads((off / "languages.json").read_text(encoding="utf-8"))
    else:
        cals, langs = calendars_online(prof["login"], now), languages_online(prof["login"])
    days = flatten(cals)
    today = et_now(now).date()  # day boundaries are US Eastern, same as the footer
    cur, best = streaks(days, today)
    last31 = [days.get(str(today - datetime.timedelta(days=i)), 0) for i in range(30, -1, -1)]
    icons = read("icons.json", {})
    tools = [t for t in read("stack.json")["tools"] if t.get("icon") in icons]  # no icon, no slot
    dates = [today - datetime.timedelta(days=i) for i in range(30, -1, -1)]
    return {"prof": prof, "tools": tools, "tokens": read("tokens.json"), "shape": read("usage-shape.json", {}), "icons": icons, "langs": langs, "days": days,
            "dates": dates, "last31": last31, "ma": ma7(days, dates), "total": sum(days.values()),
            "cur": cur, "best": best, "now": now}


def fetch_icons():
    out, skipped = {}, []
    for t in read("stack.json")["tools"]:
        slug = t.get("icon")
        try:
            svg = urllib.request.urlopen(ICON_URL.format(slug), timeout=15).read().decode()
            out[slug] = svg.split(' d="', 1)[1].split('"', 1)[0]
        except (urllib.error.HTTPError, IndexError, TypeError):
            skipped.append(t["name"])
    (ROOT / "data" / "icons.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("cached", len(out), "icons; no icon for:", skipped or "none")


# ---------------------------------------------------------------- drawing

W, M = 830, 40
IW = W - 2 * M
BG, INK, SEC, BAR, TRACK, EMPTY, RED = "#0A0A0A", "#EFEBE0", "#CDC9BE", "#A6A399", "#262522", "#3A3935", "#FF6F61"
DIM, MID, AXIS = "#7C7A72", "#BDBAAE", "#5A5953"
SHADES = [INK, "#CDC9BE", "#A6A399", "#7C7A72", "#5A5953"]  # fill brightness steps by rank
SANS = "system-ui,'Segoe UI',Helvetica,Arial,sans-serif"
DISP = "PneuMono,'JetBrains Mono',ui-monospace,Consolas,monospace"
NOTE = "Caveat,'Segoe Script','Bradley Hand',cursive"
SEED = 20261016  # fixed constant: wobble never depends on data, so shapes do not jitter between rebuilds
BANNER_H = 100
GAP = 50
LEFT_W, RX = 520, 620
RW = W - M - RX


def n(v):
    return f"{v:,}"


def clip(s, k):
    return s if len(s) <= k else s[:k - 1] + "…"


def wob(*keys):
    """Deterministic pseudo-random value in [-1, 1] from the fixed seed and integer keys."""
    x = SEED
    for k in keys:
        x = ((x ^ (k & 0xFFFFFFFF)) * 0x9E3779B1) & 0xFFFFFFFF
        x ^= x >> 15
        x = (x * 0x85EBCA6B) & 0xFFFFFFFF
        x ^= x >> 13
    return x / 0x7FFFFFFF - 1


def kid(s):
    return zlib.crc32(s.encode())


def text(x, y, s, size, fill=INK, anchor="start", weight="400", font=SANS, extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra}>{escape(s)}</text>')


def disp(x, y, s, size, fill=INK, anchor="start", extra=""):
    return text(x, y, s, size, fill, anchor, "800", DISP, extra)  # heavy display font: the name and the token hero only


def num(x, y, s, size, fill=INK):
    return text(x, y, s, size, fill, "start", "500")


def note(x, y, s, size=22, anchor="start", rot=-3):
    return text(x, y, s, size, SEC, anchor, "400", NOTE, f' transform="rotate({rot} {x} {y})"')


def fit(s, size, max_w):
    return min(size, int(max_w / (0.6 * max(len(s), 1))))  # monospace advance is 0.6 em


def title(x, y, name):
    return text(x, y, name, 18, SEC)


def et_label(now):
    local = et_now(now)
    return f"{local:%b} {local.day}, {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'} ET"


def mix(c1, c2, t):
    a, b = [int(c1[i:i + 2], 16) for i in (1, 3, 5)], [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


# ---- hand-made shapes: edges wobble perpendicular to the bar only, so bar ends stay exact

def hbar(x0, x1, yc, h, fill, key, cls="", attrs=""):
    """Horizontal bar with round ends. Top/bottom edges wobble up to ~1.4px; the ends sit exactly at x0 and x1 on the mid-line."""
    w = x1 - x0
    if w <= 0.01:
        return ""
    cl = f' class="{cls}"' if cls else ""
    if w < h:  # too short for round caps: an exact-width sliver
        return f'<rect{cl} x="{x0:.2f}" y="{yc - h / 2:.2f}" width="{w:.2f}" height="{h}" fill="{fill}"{attrs}/>'
    r = h / 2
    k = max(2, int((w - h) / 36))
    xs = [x0 + r + (w - h) * i / k for i in range(k + 1)]
    z = lambda i, s: 0 if i in (0, k) else wob(key, i, s) * 0.7
    top = [(x, yc - r + z(i, 1)) for i, x in enumerate(xs)]
    bot = [(x, yc + r + z(i, 2)) for i, x in enumerate(xs)]
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in top)
    d += f" A{r} {r} 0 0 1 {bot[-1][0]:.2f} {bot[-1][1]:.2f}" + "".join(f" L{x:.2f} {y:.2f}" for x, y in reversed(bot[:-1]))
    d += f" A{r} {r} 0 0 1 {top[0][0]:.2f} {top[0][1]:.2f}Z"
    return f'<path{cl} d="{d}" fill="{fill}"{attrs}/>'


def vbar(xc, w, ytop, ybase, fill, key, cls="", attrs="", style=""):
    """Vertical bar with a rounded top. Sides wobble up to ~1.4px; the top edge sits exactly at ytop."""
    h = ybase - ytop
    if h <= 0.01:
        return ""
    x0, x1 = xc - w / 2, xc + w / 2
    cl = f' class="{cls}"' if cls else ""
    st = f' style="{style}"' if style else ""
    r = min(4, w / 2)
    if h <= 2 * r:
        return f'<rect{cl}{st} x="{x0:.2f}" y="{ytop:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}"{attrs}/>'
    k = max(2, int((h - r) / 30))
    ys = [ybase - (h - r) * i / k for i in range(k + 1)]
    z = lambda i, s: 0 if i in (0, k) else wob(key, i, s) * 0.7
    left = [(x0 + z(i, 3), y) for i, y in enumerate(ys)]
    right = [(x1 + z(i, 4), y) for i, y in enumerate(ys)]
    d = f"M{left[0][0]:.2f} {left[0][1]:.2f}" + "".join(f" L{x:.2f} {y:.2f}" for x, y in left[1:])
    d += f" A{r} {r} 0 0 1 {x0 + r:.2f} {ytop:.2f} L{x1 - r:.2f} {ytop:.2f} A{r} {r} 0 0 1 {right[-1][0]:.2f} {right[-1][1]:.2f}"
    d += "".join(f" L{x:.2f} {y:.2f}" for x, y in reversed(right[:-1])) + "Z"
    return f'<path{cl}{st} d="{d}" fill="{fill}"{attrs}/>'


def wavy_line(x0, x1, y, key, color=AXIS, width=2):
    k = max(2, int((x1 - x0) / 40))
    pts = " ".join(f"{x0 + (x1 - x0) * i / k:.1f},{y + (0 if i in (0, k) else wob(key, i) * 0.6):.2f}" for i in range(k + 1))
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'


def tick(x, y, key, length=5):
    return (f'<line x1="{x + wob(key, 1) * 0.6:.2f}" y1="{y}" x2="{x + wob(key, 2) * 0.6:.2f}" y2="{y + length + wob(key, 3) * 1.5:.2f}" '
            f'stroke="{AXIS}" stroke-width="1.6" stroke-linecap="round"/>')


def arrow(x1, y1, x2, y2, key):
    cx, cy = (x1 + x2) / 2 + (y2 - y1) * 0.25 + wob(key, 1) * 2, (y1 + y2) / 2 - (x2 - x1) * 0.25 + wob(key, 2) * 2
    a = math.atan2(y2 - cy, x2 - cx)
    h1, h2 = (x2 - 9 * math.cos(a - 0.5), y2 - 9 * math.sin(a - 0.5)), (x2 - 9 * math.cos(a + 0.5), y2 - 9 * math.sin(a + 0.5))
    return (f'<path d="M{x1:.1f} {y1:.1f}Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}M{h1[0]:.1f} {h1[1]:.1f}L{x2:.1f} {y2:.1f}L{h2[0]:.1f} {h2[1]:.1f}" '
            f'fill="none" stroke="{SEC}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>')


# ---- banner

def noisy_path(d, key, ax, ay):
    it = iter(range(100000))

    def sub(m):
        i = next(it)
        return f"{float(m.group(1)) + wob(key, i, 5) * ax:.2f} {float(m.group(2)) + wob(key, i, 6) * ay:.2f}"
    return re.sub(r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)", sub, d)


# ---- banner: the traced double spiral at its original proportions, in its own row, as ONE continuous path
# left tip -> inward/outward coils -> S-line -> red dot (exactly on the path) -> right coils -> right tip

SPIRAL_W = 700      # the traced spiral is stretched to span most of the header width...
SPIRAL_H = 110      # ...and fits a 100-120px band
SPIRAL_CY = 62      # y of the spiral centre = the red dot = the middle of the capital letters
HEADER_H = 134      # band height including the tagline
DOT_R = 7           # radius of the red dot
TITLE_SIZE = 64     # title font size in px (the title is drawn from glyph outlines)


def parse_bez(d):
    toks = re.findall(r"[MC]|-?\d+(?:\.\d+)?", d)
    start, segs, i = None, [], 0
    while i < len(toks):
        if toks[i] == "M":
            start = (float(toks[i + 1]), float(toks[i + 2]))
            i += 3
        else:
            v = [float(t) for t in toks[i + 1:i + 7]]
            segs.append(((v[0], v[1]), (v[2], v[3]), (v[4], v[5])))
            i += 7
    return start, segs


def reverse_bez(start, segs):
    pts = [start] + [s[2] for s in segs]
    return segs[-1][2], [(c2, c1, pts[k]) for k, (c1, c2, _) in reversed(list(enumerate(segs)))]


def bez_samples(p0, c1, c2, p1, n=32):
    out, prev, total = [], p0, 0.0
    for i in range(1, n + 1):
        t, u = i / n, 1 - i / n
        x = u ** 3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p1[0]
        y = u ** 3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p1[1]
        total += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
        out.append((x, y, total))
    return total, out


def banner_geometry(d, y=0):
    """The merged spiral path in page coordinates (hand-made wobble applied), its length, the arc length to the dot, sample points."""
    lg = d["logo"]
    dx, dy, _ = lg["dot"]
    sx, sy = SPIRAL_W / 300, SPIRAL_H / 150
    cx, cy = W / 2, y + SPIRAL_CY
    T = lambda p: (cx + (p[0] - dx) * sx, cy + (p[1] - dy) * sy)
    _, lsegs = parse_bez(noisy_path(lg["left"], 0, 1.0 / sx, 1.0 / sy))      # runs dot -> left tip
    _, rsegs = parse_bez(noisy_path(lg["right"], 1, 1.0 / sx, 1.0 / sy))     # runs dot -> right tip
    start, lrev = reverse_bez((dx, dy), lsegs)                              # left tip -> dot; both arms start exactly on the dot
    lrev = [(T(a), T(b), T(c)) for a, b, c in lrev]
    rsegs = [(T(a), T(b), T(c)) for a, b, c in rsegs]
    start = T(start)
    cmd = lambda c1, c2, p: f"C{c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {p[0]:.2f} {p[1]:.2f}"
    path = f"M{start[0]:.2f} {start[1]:.2f}" + "".join(cmd(*seg) for seg in lrev) + "".join(cmd(*seg) for seg in rsegs)
    d_left = f"M{start[0]:.2f} {start[1]:.2f}" + "".join(cmd(*seg) for seg in lrev)          # left spiral centre -> outward -> S-line -> dot
    d_right = f"M{cx:.2f} {cy:.2f}" + "".join(cmd(*seg) for seg in rsegs)                    # dot -> right spiral inward to its centre (starts exactly on the dot)
    total, cur, samples, l_dot = 0.0, start, [(start[0], start[1], 0.0)], 0.0
    for part, segs in ((0, lrev), (1, rsegs)):
        for c1, c2, p in segs:
            length, pts = bez_samples(cur, c1, c2, p)
            samples += [(x, yy, total + l) for x, yy, l in pts]
            total, cur = total + length, p
        if part == 0:
            l_dot = total
    return {"d": path, "d_left": d_left, "d_right": d_right, "total": total, "l_dot": l_dot, "samples": samples, "dot": (cx, cy)}


# ---- breath: two SMIL lines (left centre -> dot, dot -> right centre) that lengthen, then collapse to nothing, plus the dot's warm-up

def smooth(x):
    return x * x * (3 - 2 * x)


def line_tail(u):
    return 1 - math.cos(math.pi * u / 2)


def line_len(u):
    """Visible length of a half (share of its pathLength) at phase progress u: head - tail with head = sin(pi u / 2), tail = 1 - cos(pi u / 2).
    0 at u = 0, about 0.41 at u = 0.5, exactly 0 again at u = 1 (head = tail = 1). Never negative."""
    return max(0.0, math.sin(math.pi * u / 2) - line_tail(u))


def kt(t):
    return f"{t / LOOP:.10g}"


def animate(attr, times, values, calc="linear", tag="animate", extra=""):
    return (f'<{tag} attributeName="{attr}"{extra} dur="{LOOP:g}s" repeatCount="indefinite" calcMode="{calc}" '
            f'keyTimes="{";".join(kt(t) for t in times)}" values="{";".join(values)}"/>')


def line_anims(s, e, peak):
    """SMIL for one overlay path active from s to e seconds of the loop: dasharray 'len 2', dashoffset -tail (STEPS+1 linear keyframes per
    phase), opacity discrete (0 outside the phase), round caps only while the segment has length."""
    pts = [(s + (e - s) * k / STEPS, k / STEPS) for k in range(STEPS + 1)]
    times = ([0.0] if s > 0 else []) + [t for t, _ in pts] + ([LOOP] if e < LOOP else [])
    us = ([None] if s > 0 else []) + [u for _, u in pts] + ([None] if e < LOOP else [])
    dash = [f"{line_len(u):.5f} 2" if u is not None else "0 2" for u in us]
    off = [f"{-line_tail(u):.5f}" if u is not None else ("0" if i == 0 else "-1") for i, u in enumerate(us)]
    otimes, ovals = ([0.0, e, LOOP], [f"{peak:g}", "0", "0"]) if s == 0 else ([0.0, s, e, LOOP], ["0", f"{peak:g}", "0", "0"])
    ctimes, cvals = [0.0, pts[1][0], e, LOOP], ["butt", "round", "butt", "butt"]
    if e == LOOP:   # the phase ends with the loop: no duplicate keyTime
        otimes, ovals, ctimes, cvals = otimes[:-1], ovals[:-1], ctimes[:-1], cvals[:-1]
    return (animate("stroke-dasharray", times, dash) + animate("stroke-dashoffset", times, off)
            + animate("opacity", otimes, ovals, "discrete") + animate("stroke-linecap", ctimes, cvals, "discrete"))


def dot_curve():
    """(times, f): f = 0 at rest, 1 at the peak. Warms from DOT_WARM, peaks exactly at LEFT_E, holds through HOLD, cosine-eases to rest across EXHALE."""
    ts, fs = [0.0], [0.0]
    for k in range(11):
        ts.append(DOT_WARM + (LEFT_E - DOT_WARM) * k / 10)
        fs.append(smooth(k / 10))
    ts.append(RIGHT_S)
    fs.append(1.0)
    for k in range(1, 25):
        ts.append(RIGHT_S + (LOOP - RIGHT_S) * k / 24)
        fs.append(0.5 + 0.5 * math.cos(math.pi * k / 24))
    return ts, fs


def grp(name, parts):
    return f'<g id="sec-{name}">' + "".join(parts) + "</g>"


def title_layout(name, size, mid_gap):
    """Lay the title out from real glyph outlines (data/title-glyphs.json, same font as the embedded display font).
    The two middle letters are pushed apart until their INK edges are mid_gap apart; the shared axis is the midpoint of that gap
    (right ink edge of the left middle letter + left ink edge of the right middle letter) / 2. Returns (letters, axis, total_width, cap_px)."""
    gl = read("title-glyphs.json")
    k = size / gl["upem"]
    chars, mid = list(name), len(name) // 2
    x, pos = 0.0, []
    for i, ch in enumerate(chars):
        g = gl["glyphs"][ch]
        if i == mid:
            x += max(0.0, mid_gap - ((x + g["bbox"][0] * k) - pos[-1]["ink_r"]))
        pos.append({"ch": ch, "x": x, "ink_l": x + g["bbox"][0] * k, "ink_r": x + g["bbox"][2] * k, "g": g})
        x += g["adv"] * k
    axis = (pos[mid - 1]["ink_r"] + pos[mid]["ink_l"]) / 2
    return pos, axis, pos[-1]["ink_r"] - pos[0]["ink_l"], gl["cap"] * k


def p_banner(d, y, css):
    """Header band, back to front: dim base lines, soft glow lines, bright lines, the dot (warms as the left line collapses into it), then the
    PNEU title, tagline and note on top so the name is legible in every frame."""
    g = banner_geometry(d, y)
    cx, cy = g["dot"]                       # the red dot: x = the title's gap axis = card centre, y = middle of the capital letters
    halves = ((g["d_left"], LEFT_S, LEFT_E), (g["d_right"], RIGHT_S, RIGHT_E))
    common = lambda dd: f'd="{dd}" pathLength="1" fill="none" stroke="{INK}" stroke-linejoin="round"'
    base = [f'<path class="base" {common(dd)} stroke-linecap="round" stroke-width="2.8" opacity=".35"/>' for dd, _, _ in halves]
    glow = [f'<path class="glow" {common(dd)} stroke-width="5.6" stroke-linecap="butt" stroke-dasharray="0 2" stroke-dashoffset="0" opacity="0">'
            + line_anims(s, e, 0.25) + "</path>" for dd, s, e in halves]
    bright = [f'<path class="bright" {common(dd)} stroke-width="2.8" stroke-linecap="butt" stroke-dasharray="0 2" stroke-dashoffset="0" opacity="0">'
              + line_anims(s, e, 1) + "</path>" for dd, s, e in halves]
    ts, fs = dot_curve()
    ring = (f'<circle class="ring" r="{DOT_R * 3}" fill="{RED}" opacity="0">' + animate("opacity", ts, [f"{0.45 * f:.4f}" for f in fs])
            + animate("transform", ts, [f"{1 + 0.25 * f:.4f}" for f in fs], tag="animateTransform", extra=' type="scale"') + "</circle>")
    core = (f'<circle class="dot" r="{DOT_R}" fill="{RED}" opacity="{DOT_REST_OPACITY}">'
            + animate("opacity", ts, [f"{DOT_REST_OPACITY + (1 - DOT_REST_OPACITY) * f:.4f}" for f in fs])
            + animate("transform", ts, [f"{1 + 0.2 * f:.4f}" for f in fs], tag="animateTransform", extra=' type="scale"') + "</circle>")
    dot = [f'<g class="dotw" transform="translate({cx:.2f} {cy:.2f})">{ring}{core}</g>',
           f'<circle class="dots" cx="{cx:.2f}" cy="{cy:.2f}" r="{DOT_R}" fill="{RED}" opacity=".8" display="none"/>']   # static dot for reduced motion
    name = clip(d["prof"]["name"].upper(), 12)
    gl = read("title-glyphs.json")
    mid_gap = 0                              # natural letter spacing: the title reads as one word, the dot sits on top of it
    title, size = [], TITLE_SIZE
    if all(c in gl["glyphs"] for c in name):
        _, _, width, _ = title_layout(name, size, mid_gap)
        size = min(size, size * (W - 2 * MG - 40) / width)
        letters, axis, width, cap = title_layout(name, size, mid_gap)
        x0, base_y = cx - axis, cy + cap / 2   # shift so the axis lands on the card centre; baseline puts the cap-height middle on the dot
        k = size / gl["upem"]
        for i, lt in enumerate(letters):
            title.append(f'<path id="t{i}-{lt["ch"]}" d="{lt["g"]["d"]}" transform="translate({x0 + lt["x"]:.2f} {base_y:.2f}) scale({k:.5f} {-k:.5f})" '
                         f'fill="{INK}" data-ink-l="{x0 + lt["ink_l"]:.2f}" data-ink-r="{x0 + lt["ink_r"]:.2f}"/>')
        title = [f'<g id="title" role="img" aria-label="{escape(name)}">' + "".join(title) + "</g>"]
    else:                                    # glyph not available: plain text on the same axis
        size = fit(name, 40, 520)
        base_y = cy + size * 0.365
        title = [disp(cx, round(base_y, 1), name, size, INK, "middle")]
    outline = f' stroke="{BG}" stroke-width="4" paint-order="stroke" stroke-linejoin="round"'
    if d["prof"].get("tagline"):
        title.append(text(cx, round(base_y + 34, 1), d["prof"]["tagline"], 18, SEC, "middle", extra=outline))   # centred under the title, same axis
    title.append(note(MG + 4, y + 30, "breathe"))
    return [grp("banner", base + glow + bright + dot + title)], HEADER_H


# ---- usage shape (daily tokens, time of day, weekday)

def short(v):
    """Abbreviated count: 1 decimal under 10, none above (1.2B, 48M, 6.3M, 208K, 950)."""
    units = [(1e9, "B"), (1e6, "M"), (1e3, "K"), (1, "")]
    for i, (div, suf) in enumerate(units):
        if v >= div:
            if not suf:
                return str(int(v))
            x = v / div
            s = f"{x:.1f}" if round(x, 1) < 10 else f"{round(x)}"
            if float(s) >= 1000 and i > 0:
                return f"{v / units[i - 1][0]:.1f}{units[i - 1][1]}"
            return s + suf
    return "0"


def label_w(t):
    """Estimated rendered width of a 16px label: digits and dots about 9px, letters (M, B, K) about 14px."""
    return sum(9.0 if c.isdigit() or c == "." else 14.5 for c in t)


def daily_labels(vals, xcs, tops, peak, today):
    """{day index: (text, x, baseline y)}. Labels above non-zero bars. On a collision: skip bars under 15% of the max, nudge neighbours
    apart by up to 7px each, then drop the smallest remaining until none touch. The peak and today are always labelled
    (today lifts 20px if it would still touch the peak)."""
    mx = max(vals)
    if mx <= 0:
        return {}
    lab = {i: short(v) for i, v in enumerate(vals) if v}
    lift, dx = {i: 0 for i in lab}, {i: 0.0 for i in lab}
    must = {peak, today} & set(lab)

    def box(i):
        w, y1, x = label_w(lab[i]), tops[i] - 6 - lift[i], xcs[i] + dx[i]
        return x - w / 2, x + w / 2, y1 - 16, y1 + 5

    def clashes():
        ids, out = sorted(lab), []
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                A, B = box(ids[a]), box(ids[b])
                if A[0] < B[1] + 3 and B[0] < A[1] + 3 and A[2] < B[3] + 1 and B[2] < A[3] + 1:
                    out.append((ids[a], ids[b]))
        return out

    def drop(i):
        del lab[i], lift[i], dx[i]

    if clashes():
        for i in list(lab):
            if i not in must and vals[i] < 0.15 * mx:
                drop(i)
    for _ in range(4 * len(lab) + 4):                      # nudge colliding neighbours apart sideways
        c = clashes()
        if not c:
            break
        a, b = c[0]
        need = (label_w(lab[a]) + label_w(lab[b])) / 2 + 3 - ((xcs[b] + dx[b]) - (xcs[a] + dx[a]))
        if need / 2 + max(abs(dx[a]), abs(dx[b])) > 7:
            break
        dx[a] -= need / 2
        dx[b] += need / 2
    while True:
        c = clashes()
        if not c:
            break
        cand = [i for pair in c for i in pair if i not in must]
        if cand:
            drop(min(cand, key=lambda k: vals[k]))
        else:
            lift[max(c[0])] += 20
    return {i: (lab[i], xcs[i] + dx[i], tops[i] - 6 - lift[i]) for i in lab}


# ---- panels: compact grid of bordered sections

PANEL, PANEL_LINE = "#121211", "#33322E"
MG, PAD, PG = 24, 12, 8       # canvas margin, panel padding, gap between panels
HM, WH, LET_DY = 54, 84, 22
HERO = 43      # token hero size: clearly under the 64px title, still the largest stat
AXIS_PX = 14   # axis letters and ticks (weekday letters, hour ticks): small enough that neighbours never touch
COL_A, COL_B, COL_C = 330, 192, 244   # shared column grid: left edges of the right-hand panels line up in every row   # daily bar max height, weekday bar max height, weekday-letter offset below a baseline


def panel(name, x, y, w, h, parts):
    return grp(name, [f'<rect class="panel" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" fill="{PANEL}" stroke="{PANEL_LINE}" stroke-width="1"/>'] + parts)


Y_STEPS = [10e6, 20e6, 25e6, 50e6, 100e6, 200e6, 250e6, 500e6, 1e9, 2e9, 5e9]
Y_MARGIN = 56   # left margin of the daily chart for the tick labels


def y_tick(v):
    return "0" if v == 0 else (f"{v / 1e9:g}B" if v >= 1e9 else f"{v / 1e6:g}M")


def sec_daily(d, x, y, w, css=None):
    sh = d.get("shape")
    if not sh:
        return [], 0
    days = sh["days"]
    vals = [v["tokens"] for v in days]
    mx, avg = max(vals + [0]), sum(vals) / max(len(vals), 1)
    peak = vals.index(mx) if mx > 0 else None
    step = next((st for st in Y_STEPS if mx <= 4 * st), Y_STEPS[-1])   # smallest nice step giving <= 4 intervals above zero
    top = max(1, math.ceil(mx / step)) * step                          # chart top: the max rounded up to the next tick
    x0, aw, BW = x + Y_MARGIN, w - Y_MARGIN - 4, 8   # plot starts right of the tick-label margin; BW: narrow enough that a centred label clears its neighbour
    pitch = aw / len(vals)
    base = y + 52 + HM   # 28px of headroom above the tallest possible bar below the title line (y + 16) plus room for its label
    out = [title(x, y + 16, "Daily tokens, last 14 days")]
    for k in range(int(top // step) + 1):   # tick label centred on its gridline; gridlines solid, 1px, 15%: unlike the dashed average
        yt = base - HM * k * step / top
        out.append(text(x + Y_MARGIN - 4, round(yt + 5.5, 1), y_tick(k * step), 16, "#CFCFCF", "end", extra=f' class="ytick" data-tick="{k * step}"'))
        if k:
            out.append(f'<line class="grid" x1="{x0 - 2}" y1="{yt:.2f}" x2="{x0 + aw + 2}" y2="{yt:.2f}" stroke="#FFFFFF" stroke-width="1" opacity="0.15" data-tick="{k * step}"/>')
    out.append(wavy_line(x0 - 2, x0 + aw + 2, base, kid("dbase")))
    xcs = [x0 + pitch * (i + 0.5) for i in range(len(vals))]
    tops = {}
    for i, (v, xc) in enumerate(zip(vals, xcs)):
        out.append(tick(xc, base + 4, kid("dt") + i, 4))
        if v == 0:
            out.append(f'<rect class="stub" x="{xc - BW / 2 + 0.75:.2f}" y="{base - 6.75:.2f}" width="{BW - 1.5:.2f}" height="6" rx="3" fill="none" stroke="{SEC}" stroke-width="1.5"/>')
            continue
        h = max(1.5, HM * v / top)
        tops[i] = base - h
        col = RED if i == peak else (DIM if v < 0.5 * avg else INK)
        out.append(vbar(xc, BW, base - h, base, col, kid("db") + i, "dbar", f' data-v="{v}" data-h="{h:.3f}" data-base="{base}" data-top="{top}"'))
    for i, xc in enumerate(xcs):
        out.append(text(round(xc, 1), base + LET_DY, "MTWTFSS"[datetime.date.fromisoformat(days[i]["date"]).weekday()], AXIS_PX, SEC, "middle"))
    ti = len(days) - 1
    out.append(f'<circle class="today" cx="{xcs[ti]:.1f}" cy="{base + LET_DY + 14}" r="3.5" fill="{INK}"/>')
    ya = base - HM * avg / top if mx > 0 else base
    bg = f' paint-order="stroke" stroke="#0A0A0A" stroke-width="5" stroke-linejoin="round"'   # cuts gridlines/the dashed line behind label text
    dash = f'stroke="{SEC}" stroke-width="1" stroke-dasharray="3 5" opacity="0.4"'
    out.append(f'<line class="avg" x1="{x0 - 2}" y1="{ya:.2f}" x2="{x0 + aw + 2}" y2="{ya:.2f}" {dash} data-avg="{avg:.3f}"/>')
    at = f"avg {short(avg)}"
    ax, tw = x + w, 9.2 * len(at)   # the average lives in the title row, right-aligned to the panel padding: dashed sample, then the text
    out.append(f'<line class="avgkey" x1="{ax - tw - 28:.1f}" y1="{y + 11:.1f}" x2="{ax - tw - 10:.1f}" y2="{y + 11:.1f}" {dash}/>' + text(round(ax, 1), y + 16, at, 16, SEC, "end"))
    shown = [k for k in dict.fromkeys((peak, ti)) if k in tops]   # only the peak (red) and today; one label when today is the peak
    for i in shown:
        hw, lift = label_w(short(vals[i])) / 2, 0
        if i != peak and peak in shown and abs(xcs[i] - xcs[peak]) < hw + label_w(short(vals[peak])) / 2 + 3:
            lift = 18   # would overlap the peak's label horizontally
        elif any(j != i and tj < tops[i] - 6 and abs(xcs[j] - xcs[i]) < hw + BW / 2 + 1 for j, tj in tops.items()):
            lift = 18   # would land on a taller neighbouring bar
        out.append(text(round(xcs[i], 1), round(tops[i] - 6 - lift, 1), short(vals[i]), 16, RED if i == peak else SEC, "middle", extra=f' data-day="{i}" data-lift="{lift}"' + bg))
    return out, LET_DY + 14 + 4 + (base - y)


def sec_tod(d, x, y, w, css=None):
    sh = d.get("shape")
    if not sh:
        return [], 0
    hours = sh["hours"]
    mh = max(hours)
    hp = hours.index(mh) if mh > 0 else None
    cp = w / 24
    out = [title(x, y + 16, "Time of day")]
    for h_ in range(24):
        c = mix("#26251F", INK, (hours[h_] / mh) ** 0.8 if mh else 0)
        out.append(f'<rect class="cell" x="{x + h_ * cp:.2f}" y="{y + 30 + wob(kid("tc"), h_) * 0.6:.2f}" width="{cp - 2:.2f}" height="48" rx="2" fill="{c}" data-h="{h_}" data-n="{hours[h_]}"/>')
    for h_, lab in ((0, "12a"), (6, "6a"), (12, "12p"), (18, "6p")):
        xt = x + h_ * cp + (cp - 2) / 2
        out += [tick(xt, y + 82, kid("th") + h_, 5), text(round(x if h_ == 0 else xt, 1), y + 106, lab, AXIS_PX, SEC, "start" if h_ == 0 else "middle")]
    if hp is not None:
        xp = min(max(x + hp * cp + cp / 2, x + 34), x + w - 34)
        out.append(text(round(xp, 1), y + 130, f"peak {hp % 12 or 12}{'a' if hp < 12 else 'p'}", 16, INK, "middle"))
    return out, 136


def sec_weekday(d, x, y, w, css=None):
    sh = d.get("shape")
    if not sh:
        return [], 0
    wk = sh["weekdays"]
    mw, nw = max(wk), min(wk)
    wbest = wk.index(mw) if mw > 0 else None
    wb, wp = y + 30 + WH, w / 7
    out = [title(x, y + 16, "By weekday")]
    for i, v in enumerate(wk):
        xc = x + wp * (i + 0.5)
        col = INK if i == wbest else (DIM if (v == nw and mw != nw) else MID)
        h = max(1.5, WH * v / mw) if v > 0 and mw > 0 else 0
        out += [vbar(xc, 16, wb - h, wb, col, kid("wd") + i, "wbar", f' data-v="{v}" data-h="{h:.3f}"') if h else
                f'<rect class="stub" x="{xc - 8.25:.2f}" y="{wb - 6.75:.2f}" width="16.5" height="6" rx="3" fill="none" stroke="{SEC}" stroke-width="1.5"/>',
                text(round(xc, 1), wb + LET_DY, "MTWTFSS"[i], AXIS_PX, SEC, "middle")]
    out.append(wavy_line(x - 2, x + w + 2, wb, kid("wbase")))
    return out, 30 + WH + LET_DY + 4


# ---- tokens, models

def shares(models, total=100):
    """Integer parts of `total` that add up to exactly `total` (largest remainder)."""
    tot = sum(models.values())
    if not tot:
        return {}
    raw = {k: v * total / tot for k, v in models.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:total - sum(out.values())]:
        out[k] += 1
    return out


def model_segments(models):
    """Rows to draw, largest first: top 4 families by name, anything under 3% folded into Other, Other only at 2% or more."""
    total = sum(models.values())
    if not total:
        return []
    fams = sorted(((k, v) for k, v in models.items() if k != "Other" and v > 0), key=lambda kv: -kv[1])
    other = models.get("Other", 0) + sum(v for _, v in fams[4:])
    top = []
    for k, v in fams[:4]:
        if v / total < 0.03:
            other += v
        else:
            top.append((k, v))
    return top + ([("Other", other)] if other / total >= 0.02 else [])


def bar_row(x0, x1, yc, h, frac, shade, key, label):
    """Track + fill whose length is exactly frac of the track; the fill carries what the pixel QC needs."""
    attrs = f' data-pct="{frac * 100:.3f}" data-t0="{x0}" data-t1="{x1}" data-yc="{yc}" data-label="{escape(label)}"'
    return (hbar(x0, x1, yc, h, TRACK, kid(key + "t"), "trk") +
            hbar(x0, x0 + (x1 - x0) * min(max(frac, 0), 1), yc, h, shade, kid(key + "f"), "fil", attrs))


def sec_tokens(d, x, y, w, css, h=None):
    tk, goal = d["tokens"], d["prof"]["goal_billions"] * 1e9
    total = tk["total"]
    frac = total / goal if goal else 0
    hs = fit(n(total), HERO, w)
    cap = 0.73 * hs                                  # digit height
    block = cap + 16 + 12                            # number + gap + progress bar
    H = max(h or 0, 30 + block + 12)
    base_y = y + max(30, (H - block) / 2) + cap      # the number and the bar are centred together in the card, below the title
    out = [title(x, y + 16, "Tokens"), disp(x, round(base_y, 1), n(total), hs)]
    by, bw = round(base_y + 16, 1), w - 136          # room for '123.5% of 10B' at the right end
    out.append(bar_row(x, x + bw, by + 6, 12, frac, RED, "goal", "goal"))
    fw = bw * min(frac, 1)
    if fw > 4:
        out += [f'<clipPath id="fc"><rect x="{x}" y="{by}" width="{fw:.2f}" height="12"/></clipPath>',
                f'<g clip-path="url(#fc)"><g class="sweep"><rect x="{x - 60}" y="{by}" width="60" height="12" fill="{INK}" opacity=".15"/>'
                f'<rect x="{x - 40}" y="{by}" width="40" height="12" fill="{INK}" opacity=".3"/>'
                f'<rect x="{x - 20}" y="{by}" width="20" height="12" fill="{INK}" opacity=".6"/></g></g>']
        css.append("@keyframes sweep{0%%{transform:translateX(0)}100%%{transform:translateX(%dpx)}}" % (fw + 60))
    out.append(f'<text x="{x + w}" y="{by + 14}" font-family="{SANS}" text-anchor="end"><tspan font-size="24" fill="{INK}">{frac * 100:.1f}%</tspan>'
               f'<tspan font-size="16" fill="{SEC}" dx="6">of {d["prof"]["goal_billions"]:g}B</tspan></text>')
    return out, H


def sec_models(d, x, y, w, css=None):
    segs = model_segments(d["tokens"].get("models") or {})
    pct = shares(dict(segs), 1000)
    out = [title(x, y + 16, "Models")]
    for i, (k, v) in enumerate(segs):
        yr = y + 30 + i * 22
        out += [text(x, yr + 16, k, 18), bar_row(x + 70, x + w - 60, yr + 10, 10, pct[k] / 1000, RED, "m" + k, k),
                text(x + w, yr + 16, f"{pct[k] / 10:.1f}%", 18, INK, "end")]
    return out, 30 + max(len(segs), 1) * 22


# ---- activity, streak, languages, stack

def fmt_mean(v):
    return f"{v:.1f}" if v < 10 else f"{round(v)}"


def sec_activity(d, x, y, w, css=None):
    vals, ma = d["last31"], d["ma"]
    mx = max(vals + [1])
    ch, base = 40, y + 100
    peak = vals.index(max(vals)) if max(vals) > 0 else None
    aw = w - 66
    pitch = aw / 31
    out = [title(x, y + 16, "Activity"),
           f'<text x="{x + w}" y="{y + 38}" font-family="{SANS}" text-anchor="end"><tspan font-size="16" fill="{SEC}">total </tspan>'
           f'<tspan font-size="{d["num_total"]}" font-weight="500" fill="{INK}">{n(d["total"])}</tspan></text>']
    for i, v in enumerate(vals):
        xc = x + i * pitch + pitch / 2
        if v == 0:
            out.append(f'<rect x="{xc - 3:.1f}" y="{base - 2}" width="6" height="2" rx="1" fill="{EMPTY}"/>')
        else:
            out.append(vbar(xc, 6, base - max(3, round(ch * v / mx)), base, INK if i == peak else BAR, kid("ab") + i, "bar", "", f"animation-delay:{i * 0.08:.2f}s"))
    if peak is not None:
        out.append(text(x + peak * pitch + pitch / 2, base - max(3, round(ch * vals[peak] / mx)) - 8, str(vals[peak]), 16, INK, "middle"))
    pts = " ".join(f"{x + i * pitch + pitch / 2:.1f},{base - ch * m / mx:.1f}" for i, m in enumerate(ma))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    mean = sum(vals) / len(vals)
    ya = base - ch * mean / mx
    out.append(f'<line class="avg2" x1="{x - 2}" y1="{ya:.2f}" x2="{x + aw + 4}" y2="{ya:.2f}" stroke="{SEC}" stroke-width="1.5" stroke-dasharray="7 6" '
               f'stroke-linecap="round" data-avg="{mean:.3f}"/>' + text(x + aw + 10, round(ya + 5, 1), f"avg {fmt_mean(mean)}", 16, SEC, "start"))
    out.append(f'<line x1="{x}" y1="{base + 20}" x2="{x + 24}" y2="{base + 20}" stroke="{INK}" stroke-width="2" stroke-linecap="round"/>'
               + text(x + 34, base + 26, "7-day avg", 16, SEC))
    return out, 100 + 30


def sec_streak(d, x, y, w, css=None):
    out = [title(x, y + 16, "Streak")]
    for xx, v, lab, col in ((x, d["cur"], "now", RED if d["cur"] else INK), (x + 86, d["best"], "best", INK)):
        out += [num(xx, y + 54, str(v), d["num_streak"], col), text(xx, y + 76, lab, 16, SEC)]
    if d["cur"] >= 3:
        out += [note(x + 66, y + 22, "on a run", 20), arrow(x + 62, y + 26, x + 30, y + 26, kid("run"))]
    return out, 82


def sec_langs(d, x, y, w, css=None):
    langs = sorted(d["langs"].items(), key=lambda kv: -kv[1])[:5]
    tot = sum(d["langs"].values())
    out = [title(x, y + 16, "Languages")]
    if not langs or not tot:
        return out + [text(x, y + 52, "No language data", 18, SEC)], 60
    for i, (name, b_) in enumerate(langs):
        ry, p = y + 30 + i * 22, b_ / tot
        out += [text(x, ry + 15, clip(name, 10), 18), bar_row(x + 104, x + w - 60, ry + 10, 10, p, RED, "l" + name, name),
                text(x + w, ry + 15, f"{p * 100:.1f}%", 18, INK, "end")]
    return out, 30 + len(langs) * 22


def sec_stack(d, x, y, w, css=None):
    tools = d["tools"]
    out = [title(x, y + 16, "Stack")]
    per = max(1, min(len(tools), int((w - 36) // 42) + 1))
    pitch = (w - 36) / (per - 1) if per > 1 else 0
    for i, t in enumerate(tools):
        out.append(f'<g transform="translate({x + (i % per) * pitch:.1f} {y + 30 + (i // per) * 44}) scale(1.5)">'
                   f'<title>{escape(t["name"])}</title><path d="{d["icons"][t["icon"]]}" fill="{INK}"/></g>')
    return out, 30 + max(1, -(-len(tools) // per)) * 44 - 8


ROWS = [  # (panel id, width or None for the remainder, section function)
    [("tokens", COL_A + COL_B + PG, sec_tokens), ("models", None, sec_models)],
    [("daily", COL_A, sec_daily), ("tod", COL_B, sec_tod), ("weekday", None, sec_weekday)],
    [("activity", COL_A + COL_B + PG, sec_activity), ("langs", None, sec_langs)],
    [("stack", COL_A + COL_B + PG, sec_stack), ("streak", None, sec_streak)],
]

def p_grid(d, y0, css):
    """Rows of bordered panels; panels in a row share a height; a row is skipped when it has no content."""
    out, y, total_w = [], y0, W - 2 * MG
    for row in ROWS:
        widths = [w for _, w, _ in row]
        rest = total_w - PG * (len(row) - 1) - sum(w for w in widths if w)
        widths = [w if w else rest for w in widths]
        built = []
        x = MG
        for (name, _, fn), w in zip(row, widths):
            parts, h = fn(d, x + PAD, y + PAD, w - 2 * PAD, [] if fn is sec_tokens else css)
            built.append((name, x, w, parts, h, fn))
            x += w + PG
        if not any(b_[4] for b_ in built):
            continue
        rh = max(b_[4] for b_ in built) + 2 * PAD
        for name, px, w, parts, h, fn in built:
            if fn is sec_tokens:                     # second pass: centre its content in the final card height (keyframes added once)
                parts, h = fn(d, px + PAD, y + PAD, w - 2 * PAD, css, rh - 2 * PAD)
            if h:
                out.append(panel(name, px, y, w, rh, parts))
        y += rh + PG
    return out, y - PG


def build(d):
    # secondary numbers never exceed half the hero, even when a long token total shrinks the hero
    d = {**d, "logo": read("logo.json"), "num_total": max(16, round(fit(n(d["tokens"]["total"]), HERO, COL_A + COL_B + PG - 2 * PAD) * 0.67)),
         "num_streak": max(16, round(fit(n(d["tokens"]["total"]), HERO, COL_A + COL_B + PG - 2 * PAD) * 0.6))}
    css = []
    banner, _ = p_banner(d, 0, css)
    grid, bottom = p_grid(d, HEADER_H + 2, css)
    parts = banner + grid
    foot = bottom + 22
    parts.append(grp("footer", [text(MG + 2, foot, f"Updated {et_label(d['now'])}", 16, SEC)]))
    height = foot + 12
    dfont, nfont = font_b64("display-font.b64"), font_b64("note-font.b64")
    static = (
        (f"@font-face{{font-family:PneuMono;font-weight:800;src:url(data:font/woff2;base64,{dfont}) format('woff2')}}" if dfont else "")
        + (f"@font-face{{font-family:Caveat;font-weight:400;src:url(data:font/woff2;base64,{nfont}) format('woff2')}}" if nfont else "")
        + "@keyframes breath-bar{0%,100%{transform:scaleY(1)}50%{transform:scaleY(1.04)}}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;animation:breath-bar 6s ease-in-out infinite}"
        ".sweep{animation:sweep 2.4s ease-in-out infinite}"
        "@media (prefers-reduced-motion:reduce){.bar{animation:none}.glow,.bright,.dotw,.sweep{display:none}.dots{display:inline}.base{opacity:.7}}")
    desc = (f"{d['prof']['name']} GitHub profile card: {len(d['tools'])} tools, {n(d['total'])} contributions, "
            f"{d['cur']} day streak, {n(d['tokens']['total'])} tokens.")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img" aria-label="{escape(desc)}">'
            f'<title>{escape(desc)}</title><style>{static}{"".join(css)}</style><defs></defs>'
            f'<rect width="{W}" height="{height}" rx="16" fill="{BG}"/>' + "".join(parts) + "</svg>\n")


def font_b64(name):
    p = ROOT / "data" / name
    return p.read_text(encoding="ascii").strip() if p.exists() else ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline")
    ap.add_argument("--fetch-icons", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "assets" / "card.svg"))
    a = ap.parse_args(argv)
    if a.fetch_icons:
        return fetch_icons()
    svg = build(gather(a.offline))
    pathlib.Path(a.out).write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {a.out} ({len(svg.encode()):,} bytes)")


if __name__ == "__main__":
    main()
