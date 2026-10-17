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

W, M = 880, 40
IW = W - 2 * M
BG, INK, SEC, BAR, TRACK, EMPTY, RED = "#0A0A0A", "#EFEBE0", "#CDC9BE", "#A6A399", "#262522", "#3A3935", "#FF6F61"
DIM, MID, AXIS = "#7C7A72", "#BDBAAE", "#5A5953"
SHADES = [INK, "#CDC9BE", "#A6A399", "#7C7A72", "#5A5953"]  # fill brightness steps by rank
SANS = "system-ui,'Segoe UI',Helvetica,Arial,sans-serif"
DISP = "PneuMono,'JetBrains Mono',ui-monospace,Consolas,monospace"
NOTE = "Caveat,'Segoe Script','Bradley Hand',cursive"
SEED = 20261016  # fixed constant: wobble never depends on data, so shapes do not jitter between rebuilds
BANNER_H = 150
GAP = 18
LEFT_W, RX = 520, 580
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


def p_banner(d, y):
    """The traced double spiral stretched into wide coils across the full width, joined by the S-line through the centre.
    Dim base + a masked bright copy: a light band sweeps left to right, the centre dot warms as it passes."""
    lg = d["logo"]
    dx, dy, _ = lg["dot"]
    sx, sy = IW / 300, 0.8
    cy = y + BANNER_H / 2
    tx, ty = M - 80 * sx, cy - dy * sy
    cx = tx + dx * sx
    paths = "".join(f'<path vector-effect="non-scaling-stroke" d="{noisy_path(lg[k], i, 1.0 / sx, 1.2 / sy)}"/>' for i, k in enumerate(("left", "right")))
    layer = (f'<g transform="translate({tx:.1f} {ty:.1f}) scale({sx:.4f} {sy})" fill="none" stroke="{INK}" stroke-width="2.8" '
             f'stroke-linecap="round" stroke-linejoin="round">{paths}</g>')
    name = clip(d["prof"]["name"].upper(), 12)
    size = fit(name, 76, 400)
    outline = f' stroke="{BG}" stroke-width="5" paint-order="stroke" stroke-linejoin="round"'
    out = [f'<g opacity=".3">{layer}</g>', f'<g class="lit" mask="url(#bm)">{layer}</g>',
           f'<circle class="ring" cx="{cx:.1f}" cy="{cy}" r="34" fill="{RED}" opacity="0"/>',
           f'<circle class="dotw" cx="{cx:.1f}" cy="{cy}" r="9" fill="{RED}" opacity=".22"/>',
           disp(W / 2, round(cy + size * 0.37 - 4), name, size, INK, "middle", outline)]
    if d["prof"].get("tagline"):
        out.append(text(W / 2, y + BANNER_H - 12, d["prof"]["tagline"], 18, SEC, "middle", extra=outline.replace('stroke-width="5"', 'stroke-width="4"')))
    out.append(note(M + 6, y + 30, "breathe"))
    return out, BANNER_H


# ---- tokens

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


def bar_row(x0, x1, yc, h, frac, shade, key, label, extra_track=""):
    """Track + fill whose length is exactly frac of the track; the fill carries what the pixel QC needs."""
    attrs = f' data-pct="{frac * 100:.3f}" data-t0="{x0}" data-t1="{x1}" data-yc="{yc}" data-label="{escape(label)}"'
    return (hbar(x0, x1, yc, h, TRACK, kid(key + "t"), "trk") +
            hbar(x0, x0 + (x1 - x0) * min(max(frac, 0), 1), yc, h, shade, kid(key + "f"), "fil", attrs))


def p_tokens(d, y, css):
    tk, goal = d["tokens"], d["prof"]["goal_billions"] * 1e9
    total = tk["total"]
    frac = total / goal if goal else 0
    out = [title(M, y + 16, "Tokens"), disp(M, y + 92, n(total), fit(n(total), 88, IW))]
    by, bw = y + 112, IW - 156
    out.append(bar_row(M, M + bw, by + 6, 12, frac, INK, "goal", "goal"))
    fw = bw * min(frac, 1)
    if fw > 4:
        out += [f'<clipPath id="fc"><rect x="{M}" y="{by}" width="{fw:.2f}" height="12"/></clipPath>',
                f'<g clip-path="url(#fc)"><g class="sweep"><rect x="{M - 60}" y="{by}" width="60" height="12" fill="{RED}" opacity=".15"/>'
                f'<rect x="{M - 40}" y="{by}" width="40" height="12" fill="{RED}" opacity=".3"/>'
                f'<rect x="{M - 20}" y="{by}" width="20" height="12" fill="{RED}" opacity=".6"/></g></g>']
        css.append("@keyframes sweep{0%%{transform:translateX(0)}100%%{transform:translateX(%dpx)}}" % (fw + 60))
    out.append(f'<text x="{W - M}" y="{by + 14}" font-family="{SANS}" text-anchor="end"><tspan font-size="24" fill="{INK}">{frac * 100:.1f}%</tspan>'
               f'<tspan font-size="16" fill="{SEC}" dx="8">of {d["prof"]["goal_billions"]:g}B</tspan></text>')
    segs = model_segments(tk.get("models") or {})
    pct = shares(dict(segs), 1000)
    ry = by + 40
    for i, (k, v) in enumerate(segs):
        yr = ry + i * 30
        out += [text(M, yr + 16, k, 18), bar_row(M + 110, W - M - 76, yr + 10, 10, pct[k] / 1000, SHADES[i], "m" + k, k),
                text(W - M, yr + 16, f"{pct[k] / 10:.1f}%", 18, INK, "end")]
    return out, (ry - y) + max(len(segs), 1) * 30


# ---- usage shape (daily tokens, time of day, weekday)

def p_shape(d, y):
    sh = d.get("shape")
    if not sh:
        return [], 0
    days = sh["days"]
    vals = [x["tokens"] for x in days]
    mx, avg = max(vals + [0]), sum(vals) / max(len(vals), 1)
    peak = vals.index(mx) if mx > 0 else None
    HM, base, aw = 110, y + 160, 470
    pitch = aw / len(vals)
    out = [title(M, y + 16, "Daily tokens, last 14 days"), wavy_line(M - 2, M + aw + 2, base, kid("dbase"))]
    xcs = [M + pitch * (i + 0.5) for i in range(len(vals))]
    top = None
    for i, (v, x) in enumerate(zip(vals, xcs)):
        out.append(tick(x, base + 4, kid("dt") + i, 4))
        if v == 0:
            out.append(f'<rect class="stub" x="{x - 10.25:.2f}" y="{base - 6.75:.2f}" width="20.5" height="6" rx="3" fill="none" stroke="{SEC}" stroke-width="1.5"/>')
            continue
        h = max(1.5, HM * v / mx)
        col = RED if i == peak else (DIM if v < 0.5 * avg else INK)
        out.append(vbar(x, 22, base - h, base, col, kid("db") + i, "dbar", f' data-v="{v}" data-h="{h:.3f}" data-base="{base}"'))
        if i == peak:
            top = base - h
    letters = "MTWTFSS"
    for i, x in enumerate(xcs):
        wd = datetime.date.fromisoformat(days[i]["date"]).weekday()
        out.append(text(round(x, 1), base + 28, letters[wd], 16, SEC, "middle"))
    ti = len(days) - 1
    out.append(f'<circle class="today" cx="{xcs[ti]:.1f}" cy="{base + 42}" r="3.5" fill="{INK}"/>')
    ya = base - HM * avg / mx if mx > 0 else base
    out.append(f'<line class="avg" x1="{M - 2}" y1="{ya:.2f}" x2="{M + aw + 4}" y2="{ya:.2f}" stroke="{SEC}" stroke-width="1.5" stroke-dasharray="7 6" '
               f'stroke-linecap="round" data-avg="{avg:.3f}"/>' + text(M + LEFT_W, round(ya + 5, 1), "avg", 16, SEC, "end"))
    out.append(text(M, base + 74, "hollow = no usage", 16, SEC))
    if peak is not None:
        out.append(text(round(xcs[peak], 1), round(top - 8, 1), "peak", 16, RED, "middle"))
        if xcs[peak] > M + 380:
            out += [note(xcs[peak] - 34, top - 30, "best day", 22, "end"), arrow(xcs[peak] - 30, top - 22, xcs[peak] - 14, top + 6, kid("bd"))]
        else:
            out += [note(xcs[peak] + 34, top - 30, "best day"), arrow(xcs[peak] + 30, top - 22, xcs[peak] + 14, top + 6, kid("bd"))]
    # time of day
    hours = sh["hours"]
    mh = max(hours)
    hp = hours.index(mh) if mh > 0 else None
    cp = RW / 24
    out.append(title(RX, y + 16, "Time of day"))
    for h_ in range(24):
        c = RED if h_ == hp else mix("#1E1D1A", INK, (hours[h_] / mh) ** 0.8 if mh else 0)
        out.append(f'<rect class="cell" x="{RX + h_ * cp:.2f}" y="{y + 30 + wob(kid("tc"), h_) * 0.6:.2f}" width="{cp - 2.4:.2f}" height="36" rx="2" fill="{c}" data-h="{h_}" data-n="{hours[h_]}"/>')
    for h_, lab in ((0, "12a"), (6, "6a"), (12, "12p"), (18, "6p")):
        x = RX + h_ * cp + (cp - 2.4) / 2
        out += [tick(x, y + 70, kid("th") + h_, 5), text(round(x - (cp - 2.4) / 2 if h_ == 0 else x, 1), y + 98, lab, 16, SEC, "start" if h_ == 0 else "middle")]
    if hp is not None:
        lab = f"peak {hp % 12 or 12}{'a' if hp < 12 else 'p'}"
        xp = min(max(RX + hp * cp + cp / 2, RX + 40), W - M - 40)
        out.append(text(round(xp, 1), y + 122, lab, 16, RED, "middle"))
    # weekday
    wk = sh["weekdays"]
    mw, nw = max(wk), min(wk)
    wbest = wk.index(mw) if mw > 0 else None
    wb, wh, wp = y + 214, 56, RW / 7
    out.append(title(RX, y + 148, "By weekday"))
    for i, v in enumerate(wk):
        xc = RX + wp * (i + 0.5)
        col = INK if i == wbest else (DIM if (v == nw and mw != nw) else MID)
        h = max(1.5, wh * v / mw) if v > 0 and mw > 0 else 0
        out += [vbar(xc, 26, wb - h, wb, col, kid("wd") + i, "wbar", f' data-v="{v}" data-h="{h:.3f}"') if h else
                f'<rect class="stub" x="{xc - 12.25:.2f}" y="{wb - 6.75:.2f}" width="24.5" height="6" rx="3" fill="none" stroke="{SEC}" stroke-width="1.5"/>',
                text(round(xc, 1), wb + 24, "MTWTFSS"[i], 16, SEC, "middle")]
    out.append(wavy_line(RX - 2, W - M + 2, wb, kid("wbase")))
    return out, 244


# ---- activity, streak, languages, stack

def p_contrib(d, y):
    vals, ma = d["last31"], d["ma"]
    mx = max(vals + [1])
    ch, base = 56, y + 118
    peak = vals.index(max(vals)) if max(vals) > 0 else None
    pitch = LEFT_W / 31
    out = [title(M, y + 16, "Activity"),
           f'<text x="{M + LEFT_W}" y="{y + 34}" font-family="{SANS}" text-anchor="end"><tspan font-size="16" fill="{SEC}">total </tspan>'
           f'<tspan font-size="36" font-weight="500" fill="{INK}">{n(d["total"])}</tspan></text>']
    for i, v in enumerate(vals):
        x = M + i * pitch + pitch / 2
        if v == 0:
            out.append(f'<rect x="{x - 3:.1f}" y="{base - 2}" width="6" height="2" rx="1" fill="{EMPTY}"/>')
        else:
            out.append(vbar(x, 6, base - max(3, round(ch * v / mx)), base, RED if i == peak else BAR, kid("ab") + i, "bar", "", f"animation-delay:{i * 0.08:.2f}s"))
    if peak is not None:
        out.append(text(M + peak * pitch + pitch / 2, base - max(3, round(ch * vals[peak] / mx)) - 8, str(vals[peak]), 16, INK, "middle"))
    pts = " ".join(f"{M + i * pitch + pitch / 2:.1f},{base - ch * m / mx:.1f}" for i, m in enumerate(ma))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    out.append(f'<line x1="{M}" y1="{base + 28}" x2="{M + 24}" y2="{base + 28}" stroke="{INK}" stroke-width="2" stroke-linecap="round"/>'
               + text(M + 34, base + 33, "7-day avg", 16, SEC))
    out.append(title(RX, y + 16, "Streak"))
    for x, v, lab, col in ((RX, d["cur"], "now", RED if d["cur"] else INK), (RX + 130, d["best"], "best", INK)):
        out += [num(x, y + 74, str(v), 40, col), text(x, y + 100, lab, 16, SEC)]
    if d["cur"] >= 3:
        out += [note(RX + 70, y + 40, "on a run"), arrow(RX + 66, y + 44, RX + 34, y + 54, kid("run"))]
    return out, 152


def p_langs_stack(d, y):
    langs = sorted(d["langs"].items(), key=lambda kv: -kv[1])[:5]
    tot = sum(d["langs"].values())
    out = [title(M, y + 16, "Languages")]
    lang_h = 40
    if not langs or not tot:
        out.append(text(M, y + 52, "No language data", 18, SEC))
    else:
        bx, bw = M + 150, 280
        for i, (name, b) in enumerate(langs):
            ry, p = y + 34 + i * 26, b / tot
            out += [text(M, ry + 14, clip(name, 14), 18), bar_row(bx, bx + bw, ry + 9, 10, p, INK if i == 0 else BAR, "l" + name, name),
                    text(M + LEFT_W, ry + 14, f"{p * 100:.1f}%", 18, INK, "end")]
        lang_h = 34 + len(langs) * 26
    tools = d["tools"]
    out.append(title(RX, y + 16, "Stack"))
    for i, t in enumerate(tools):
        out.append(f'<g transform="translate({RX + (i % 4) * 64} {y + 38 + (i // 4) * 44}) scale(1.5)">'
                   f'<title>{escape(t["name"])}</title><path d="{d["icons"][t["icon"]]}" fill="{INK}"/></g>')
    return out, max(lang_h, 38 + max(1, -(-len(tools) // 4)) * 44 - 8)


def font_b64(name):
    p = ROOT / "data" / name
    return p.read_text(encoding="ascii").strip() if p.exists() else ""


def build(d):
    d = {**d, "logo": read("logo.json")}
    css = []
    parts, y = [], 0
    for fn in (p_banner, p_tokens, p_shape, p_contrib, p_langs_stack):
        out, h = fn(d, y, css) if fn is p_tokens else fn(d, y)
        parts += out
        y += h + (GAP if h else 0)
    foot = y - GAP + 30
    parts.append(text(M, foot, f"Updated {et_label(d['now'])}", 16, SEC))
    height = foot + 14
    dfont, nfont = font_b64("display-font.b64"), font_b64("note-font.b64")
    static = (
        (f"@font-face{{font-family:PneuMono;font-weight:800;src:url(data:font/woff2;base64,{dfont}) format('woff2')}}" if dfont else "")
        + (f"@font-face{{font-family:Caveat;font-weight:400;src:url(data:font/woff2;base64,{nfont}) format('woff2')}}" if nfont else "")
        + "@keyframes band{0%{transform:translateX(0)}100%{transform:translateX(1140px)}}"
        "@keyframes warm{0%,25%{opacity:.22;transform:scale(1)}45%,55%{opacity:.95;transform:scale(1.18)}80%,100%{opacity:.22;transform:scale(1)}}"
        "@keyframes ring{0%,25%{opacity:0}45%,55%{opacity:.5}80%,100%{opacity:0}}"
        "@keyframes breath-bar{0%,100%{transform:scaleY(1)}50%{transform:scaleY(1.04)}}"
        ".band{animation:band 6s linear infinite}"
        ".dotw{transform-box:fill-box;transform-origin:center;animation:warm 6s ease-in-out infinite}"
        ".ring{animation:ring 6s ease-in-out infinite}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;animation:breath-bar 6s ease-in-out infinite}"
        ".sweep{animation:sweep 2.4s ease-in-out infinite}"
        "@media (prefers-reduced-motion:reduce){.band,.dotw,.ring,.bar{animation:none}.lit{mask:none}.dotw{opacity:.7}.ring{opacity:.25}.sweep{display:none}}")
    desc = (f"{d['prof']['name']} GitHub profile card: {len(d['tools'])} tools, {n(d['total'])} contributions, "
            f"{d['cur']} day streak, {n(d['tokens']['total'])} tokens.")
    defs = (f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000"/><stop offset=".5" stop-color="#fff"/>'
            f'<stop offset="1" stop-color="#000"/></linearGradient>'
            f'<mask id="bm" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{BANNER_H}"><g class="band">'
            f'<rect x="-260" y="0" width="260" height="{BANNER_H}" fill="url(#bg)"/></g></mask>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img" aria-label="{escape(desc)}">'
            f'<title>{escape(desc)}</title><style>{static}{"".join(css)}</style><defs>{defs}</defs>'
            f'<rect width="{W}" height="{height}" rx="16" fill="{BG}"/>' + "".join(parts) + "</svg>\n")


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
