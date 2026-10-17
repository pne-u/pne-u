#!/usr/bin/env python3
"""Draws assets/card.svg ("breath" design) from data/*.json, the GitHub contribution calendar and language bytes.

  python scripts/build_card.py                 online: gh api (GH_TOKEN or a logged-in gh)
  python scripts/build_card.py --offline DIR   DIR/contributions.json + DIR/languages.json, no network
  python scripts/build_card.py --fetch-icons   cache simple-icons paths into data/icons.json

Stdlib only. The SVG has no scripts, no external requests, no web fonts: a monospace system stack and
inlined icon paths, one OFL display font subset (data/display-font.b64). Own #0A0A0A background, so it reads the
same in light and dark mode. Motion is CSS inside the SVG and is off under prefers-reduced-motion.
"""
import argparse, datetime, json, pathlib, subprocess, urllib.error, urllib.request
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
    return {"prof": prof, "tools": tools, "tokens": read("tokens.json"), "icons": icons, "langs": langs, "days": days,
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
BG, WHITE, SEC, BAR, TRACK, EMPTY, RED = "#0A0A0A", "#FFFFFF", "#CFCFCF", "#A8A8A8", "#262626", "#3A3A3A", "#FF6F61"
LOGO_RED = "#E5222B"  # the logo dot keeps the red of the original image; text-safe coral is used elsewhere
SANS = "system-ui,'Segoe UI',Helvetica,Arial,sans-serif"
DISP = "PneuMono,'JetBrains Mono',ui-monospace,Consolas,monospace"
SEGC = ["#FFFFFF", "#C4C4C4", "#8A8A8A", "#5C5C5C", "#3C3C3C"]  # model-bar greys, largest share first
SPAN = 140  # width of the token-bar sweep highlight
GAP = 18  # whitespace between rows
LEFT_W = 520  # left column of the two-column rows; the right column starts at RX
RX = 580
LABEL_W = 8.8  # estimated width of one 16px label character


def n(v):
    return f"{v:,}"


def clip(s, k):
    return s if len(s) <= k else s[:k - 1] + "…"


def text(x, y, s, size, fill=WHITE, anchor="start", weight="400", font=SANS):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{escape(s)}</text>')


def disp(x, y, s, size, fill=WHITE):
    return text(x, y, s, size, fill, "start", "800", DISP)  # display font, heavy: the name and the token hero only


def num(x, y, s, size, fill=WHITE):
    return text(x, y, s, size, fill, "start", "500")  # every other number: system sans, medium


def fit(s, size, max_w):
    return min(size, int(max_w / (0.6 * max(len(s), 1))))  # monospace advance is 0.6 em


def title(x, y, name):
    return text(x, y, name, 18, SEC)


def et_label(now):
    """'Oct 16, 9:31 PM ET'"""
    local = et_now(now)
    return f"{local:%b} {local.day}, {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'} ET"


def logo(x, y, scale, d):
    """Traced logo (data/logo.json) at its original proportions (uniform scale): two gradient spiral arms and a separate red dot."""
    lg = d["logo"]
    cx, cy, r = lg["dot"]
    tx, ty = x - 80 * scale, y - 155 * scale
    return (f'<g transform="translate({tx:.2f} {ty:.2f}) scale({scale})">'
            f'<g class="glow"><circle cx="{cx}" cy="{cy}" r="34" fill="{LOGO_RED}" fill-opacity=".10"/>'
            f'<circle cx="{cx}" cy="{cy}" r="22" fill="{LOGO_RED}" fill-opacity=".22"/></g>'
            f'<g fill="none" stroke-width="{lg["stroke"]}" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="{lg["left"]}" stroke="url(#gl)"/><path d="{lg["right"]}" stroke="url(#gr)"/></g>'
            f'<circle class="dot" cx="{cx}" cy="{cy}" r="{r}" fill="{LOGO_RED}"/></g>')


def p_header(d, y):
    prof = d["prof"]
    nx = M + 150 + 36  # logo is 150 wide at scale .5, then clear space so the name reads as one word
    name = clip(prof["name"].upper(), (W - M - nx) * 10 // 240)
    size = fit(name, 64, W - M - nx)
    out = [logo(M, y + 16, 0.5, d), disp(nx, y + 77, name, size)]
    tx = nx + len(name) * 0.6 * size + 24
    if prof.get("tagline") and tx + len(prof["tagline"]) * 9.6 <= W - M:  # only when it fits on the name's line
        out.append(text(tx, y + 77, prof["tagline"], 18, SEC))
    return out, 98


def shares(models):
    """Integer percentages that add up to exactly 100 (largest remainder)."""
    tot = sum(models.values())
    if not tot:
        return {}
    raw = {k: v * 100 / tot for k, v in models.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:100 - sum(out.values())]:
        out[k] += 1
    return out


def model_segments(models):
    """Segments to draw, largest share first: top 4 families by name, anything under 3% folded into Other,
    Other only when it is 2% or more. [(name, tokens)]"""
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


def segment_layout(segs):
    """[(name, tokens, x, width, percent)] across the full width, 2px gaps, widths exactly proportional to share."""
    drawn = sum(v for _, v in segs)
    pct = shares(dict(segs))
    avail = IW - 2 * (len(segs) - 1)
    x, out = M, []
    for k, v in segs:
        w = avail * v / drawn
        out.append((k, v, x, w, pct[k]))
        x += w + 2
    return out


def label_rows(layout):
    """Row index per label: left-aligned at its segment start; drop to a lower row when it would touch the previous label."""
    ends, rows = [], []
    for k, _, x, w, pct in layout:
        r = 0
        while r < len(ends) and ends[r] + 10 > x:
            r += 1
        if r == len(ends):
            ends.append(0)
        ends[r] = x + len(f"{k} {pct}%") * LABEL_W
        rows.append(r)
    return rows


def p_tokens(d, y, css):
    tk, goal = d["tokens"], d["prof"]["goal_billions"] * 1e9
    total = tk["total"]
    frac = min(1, total / goal) if goal else 0
    pct = f"{total / goal * 100:.1f}%" if goal else "0.0%"
    out = [title(M, y + 16, "Tokens"), disp(M, y + 92, n(total), fit(n(total), 88, IW))]
    by, bw = y + 112, IW - 156
    fw = max(12, round(bw * frac)) if frac else 0
    out.append(f'<rect x="{M}" y="{by}" width="{bw}" height="12" rx="6" fill="{TRACK}"/>')
    if fw:
        out += [f'<clipPath id="fc"><rect x="{M}" y="{by}" width="{fw}" height="12" rx="6"/></clipPath>',
                f'<rect class="fill" x="{M}" y="{by}" width="{fw}" height="12" rx="6" fill="{WHITE}"/>',
                f'<g clip-path="url(#fc)"><rect class="sweep" x="{M - SPAN}" y="{by}" width="{SPAN}" height="12" fill="url(#sw)"/></g>']
        css.append("@keyframes sweep{0%%{transform:translateX(0)}100%%{transform:translateX(%dpx)}}" % (fw + SPAN))
    out.append(f'<text x="{W - M}" y="{by + 14}" font-family="{SANS}" text-anchor="end"><tspan font-size="24" fill="{WHITE}">{pct}</tspan>'
               f'<tspan font-size="16" fill="{SEC}" dx="8">of {d["prof"]["goal_billions"]:g}B</tspan></text>')
    h = by - y + 12
    segs = model_segments(tk.get("models") or {})
    if segs:
        sy = by + 30
        layout = segment_layout(segs)
        out.append(f'<clipPath id="mb"><rect x="{M}" y="{sy}" width="{IW}" height="20" rx="10"/></clipPath><g clip-path="url(#mb)">')
        for i, (k, v, x, w, p) in enumerate(layout):
            out.append(f'<rect class="mseg" data-name="{escape(k)}" x="{x:.2f}" y="{sy}" width="{w:.2f}" height="20" fill="{SEGC[i]}"/>')
        out.append("</g>")
        rows = label_rows(layout)
        for (k, v, x, w, p), r in zip(layout, rows):
            right = x + len(f"{k} {p}%") * LABEL_W > W - M  # a late segment can start too far right for a left-aligned label
            out.append(text(W - M if right else round(x, 2), sy + 40 + r * 24, f"{k} {p}%", 16, SEC, "end" if right else "start"))
        h = sy - y + 40 + max(rows) * 24 + 6
    return out, h


def p_contrib(d, y):
    """Left: Activity, 31-day bars with the 7-day average and the all-time total. Right: Streak, now and best."""
    vals, ma = d["last31"], d["ma"]
    mx = max(vals + [1])
    ch, base = 56, y + 118
    peak = vals.index(max(vals)) if max(vals) > 0 else None
    pitch = LEFT_W / 31
    out = [title(M, y + 16, "Activity"),
           f'<text x="{M + LEFT_W}" y="{y + 34}" font-family="{SANS}" text-anchor="end"><tspan font-size="16" fill="{SEC}">total </tspan>'
           f'<tspan font-size="36" font-weight="500" fill="{WHITE}">{n(d["total"])}</tspan></text>']
    for i, v in enumerate(vals):
        x = M + i * pitch + (pitch - 6) / 2
        if v == 0:
            out.append(f'<rect x="{x:.1f}" y="{base - 2}" width="6" height="2" rx="1" fill="{EMPTY}"/>')
        else:
            bh = max(5, round(ch * v / mx))
            out.append(f'<rect class="bar" x="{x:.1f}" y="{base - bh}" width="6" height="{bh}" rx="3" '
                       f'fill="{RED if i == peak else BAR}" style="animation-delay:{i * 0.08:.2f}s"/>')
    if peak is not None:
        out.append(text(M + peak * pitch + pitch / 2, base - round(ch * vals[peak] / mx) - 8, str(vals[peak]), 16, WHITE, "middle"))
    pts = " ".join(f"{M + i * pitch + pitch / 2:.1f},{base - ch * m / mx:.1f}" for i, m in enumerate(ma))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{WHITE}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    out.append(f'<line x1="{M}" y1="{base + 28}" x2="{M + 24}" y2="{base + 28}" stroke="{WHITE}" stroke-width="2" stroke-linecap="round"/>'
               + text(M + 34, base + 33, "7-day avg", 16, SEC))
    out.append(title(RX, y + 16, "Streak"))
    for x, v, lab, col in ((RX, d["cur"], "now", RED if d["cur"] else WHITE), (RX + 130, d["best"], "best", WHITE)):
        out += [num(x, y + 74, str(v), 40, col), text(x, y + 100, lab, 16, SEC)]
    return out, 152


def p_langs_stack(d, y):
    """Left: top 5 languages by bytes. Right: tool icons in a small grid."""
    langs = sorted(d["langs"].items(), key=lambda kv: -kv[1])[:5]
    tot = sum(d["langs"].values())
    out = [title(M, y + 16, "Languages")]
    lang_h = 40
    if not langs or not tot:
        out.append(text(M, y + 52, "No language data", 18, SEC))
    else:
        bx, bw = M + 150, 280
        for i, (name, b) in enumerate(langs):
            ry, pct = y + 34 + i * 26, b / tot
            out += [text(M, ry + 14, clip(name, 14), 18), f'<rect x="{bx}" y="{ry + 4}" width="{bw}" height="10" rx="5" fill="{TRACK}"/>',
                    f'<rect x="{bx}" y="{ry + 4}" width="{max(10, round(bw * pct))}" height="10" rx="5" fill="{WHITE if i == 0 else BAR}"/>',
                    text(M + LEFT_W, ry + 14, f"{pct * 100:.1f}%", 18, WHITE, "end")]
        lang_h = 34 + len(langs) * 26
    tools = d["tools"]
    out.append(title(RX, y + 16, "Stack"))
    for i, t in enumerate(tools):
        out.append(f'<g transform="translate({RX + (i % 4) * 64} {y + 38 + (i // 4) * 44}) scale(1.5)">'
                   f'<title>{escape(t["name"])}</title><path d="{d["icons"][t["icon"]]}" fill="{WHITE}"/></g>')
    stack_h = 38 + max(1, -(-len(tools) // 4)) * 44 - 8
    return out, max(lang_h, stack_h)


def font_b64():
    p = ROOT / "data" / "display-font.b64"
    return p.read_text(encoding="ascii").strip() if p.exists() else ""


def build(d):
    d = {**d, "logo": read("logo.json")}
    css = []
    parts, y = [], 0
    for fn in (p_header, p_tokens, p_contrib, p_langs_stack):  # usage first, tools last
        out, h = fn(d, y, css) if fn is p_tokens else fn(d, y)
        parts += out
        y += h + GAP
    foot = y - GAP + 30
    parts.append(text(M, foot, f"Updated {et_label(d['now'])}", 16, SEC))
    height = foot + 14
    font = font_b64()
    static = (
        (f"@font-face{{font-family:PneuMono;font-weight:800;src:url(data:font/woff2;base64,{font}) format('woff2')}}" if font else "")
        + "@keyframes breath-dot{0%,100%{transform:scale(1)}50%{transform:scale(1.25)}}"
        "@keyframes breath-glow{0%,100%{opacity:.45}50%{opacity:1}}"
        "@keyframes breath-bar{0%,100%{transform:scaleY(1)}50%{transform:scaleY(1.04)}}"
        "@keyframes breath-fill{0%,100%{opacity:.86}50%{opacity:1}}"
        ".dot{transform-box:fill-box;transform-origin:center;animation:breath-dot 6s ease-in-out infinite}"
        ".glow{animation:breath-glow 6s ease-in-out infinite}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;animation:breath-bar 6s ease-in-out infinite}"
        ".fill{animation:breath-fill 6s ease-in-out infinite}"
        ".sweep{animation:sweep 2.4s ease-in-out infinite}"
        "@media (prefers-reduced-motion:reduce){.dot,.glow,.bar,.fill{animation:none}.sweep{display:none}}")
    desc = (f"{d['prof']['name']} GitHub profile card: {len(d['tools'])} tools, {n(d['total'])} contributions, "
            f"{d['cur']} day streak, {n(d['tokens']['total'])} tokens.")
    defs = ('<linearGradient id="gl" gradientUnits="userSpaceOnUse" x1="229" y1="0" x2="80" y2="0"><stop offset="0" stop-color="#E6E6E6"/>'
            '<stop offset="1" stop-color="#777777"/></linearGradient>'
            '<linearGradient id="gr" gradientUnits="userSpaceOnUse" x1="229" y1="0" x2="378" y2="0"><stop offset="0" stop-color="#E6E6E6"/>'
            '<stop offset="1" stop-color="#797979"/></linearGradient>'
            f'<linearGradient id="sw" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{RED}" stop-opacity="0"/>'
            f'<stop offset=".55" stop-color="{RED}" stop-opacity=".3"/><stop offset=".88" stop-color="{RED}" stop-opacity=".95"/>'
            f'<stop offset="1" stop-color="{RED}" stop-opacity="0"/></linearGradient>')
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
