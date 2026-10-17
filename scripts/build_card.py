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
    today = now.date()
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
BG, WHITE, SEC, BAR, TRACK, EMPTY, RED = "#0A0A0A", "#FFFFFF", "#CFCFCF", "#A8A8A8", "#262626", "#3A3A3A", "#FF6F61"
SANS = "system-ui,'Segoe UI',Helvetica,Arial,sans-serif"
DISP = "PneuMono,'JetBrains Mono',ui-monospace,Consolas,monospace"
SEG = ["#FFFFFF", "#BDBDBD", "#7C7C7C", "#4C4C4C"]  # token-model segments, decorative
SPAN = 140  # width of the token-bar sweep highlight
GAP = 18  # whitespace between rows
LEFT_W = 520  # left column of the two-column rows; the right column starts at RX
RX = 580


def n(v):
    return f"{v:,}"


def clip(s, k):
    return s if len(s) <= k else s[:k - 1] + "…"


def text(x, y, s, size, fill=WHITE, anchor="start", weight="400", font=SANS):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{escape(s)}</text>')


def disp(x, y, s, size, fill=WHITE, anchor="start"):
    return text(x, y, s, size, fill, anchor, "800", DISP)


def fit(s, size, max_w):
    return min(size, int(max_w / (0.6 * max(len(s), 1))))  # monospace advance is 0.6 em


def title(x, y, name, meta="", right=0):
    return text(x, y, name, 22, WHITE, weight="700") + (text(right, y, meta, 16, SEC, "end") if meta else "")


def et_label(now):
    """US Eastern, e.g. 'Oct 16, 9:31 PM EDT'. Own DST rule so no tz database is needed."""
    def nth_sunday(year, month, nth, hour):
        d = datetime.datetime(year, month, 1, hour, tzinfo=datetime.timezone.utc)
        return d + datetime.timedelta(days=(6 - d.weekday()) % 7 + 7 * (nth - 1))
    dst = nth_sunday(now.year, 3, 2, 7) <= now < nth_sunday(now.year, 11, 1, 6)
    local = now + datetime.timedelta(hours=-4 if dst else -5)
    return f"{local:%b} {local.day}, {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'} {'EDT' if dst else 'EST'}"


def banner(d, cy):
    """The traced double spiral (data/logo.json) stretched across the card as a dim backdrop, centred on cy.
    The strokes keep a constant width (non-scaling-stroke); the red dot and its glow stay round and sit where the arms cross."""
    lg = d["logo"]
    dx, dy, r = lg["dot"]
    sx, sy = 2.55, 0.56
    tx, ty = W / 2 - dx * sx, cy - dy * sy
    return (f'<g transform="translate({tx:.1f} {ty:.1f}) scale({sx} {sy})" fill="none" stroke-width="3.5" '
            f'stroke-linecap="round" stroke-linejoin="round" opacity=".62">'
            f'<path vector-effect="non-scaling-stroke" d="{lg["left"]}" stroke="url(#gl)"/>'
            f'<path vector-effect="non-scaling-stroke" d="{lg["right"]}" stroke="url(#gr)"/></g>'
            f'<g class="glow"><circle cx="{W / 2}" cy="{cy}" r="44" fill="{RED}" fill-opacity=".08"/>'
            f'<circle cx="{W / 2}" cy="{cy}" r="28" fill="{RED}" fill-opacity=".2"/></g>'
            f'<circle class="dot" cx="{W / 2}" cy="{cy}" r="10" fill="{RED}"/>')


def p_header(d, y):
    prof = d["prof"]
    name = clip(prof["name"].upper(), (W - 2 * M - 60) * 10 // 240)  # at most this many chars so the name stays 40px or larger
    size = fit(name, 60, W - 2 * M - 60)
    cy, half = y + 62, len(name) // 2
    base = cy + int(size * 0.37)
    return [banner(d, cy), disp(W / 2 - 30, base, name[:half], size, WHITE, "end"),  # the name opens around the red dot
            disp(W / 2 + 30, base, name[half:], size, WHITE, "start"),
            text(W / 2, y + 124, prof["tagline"], 18, SEC, "middle")], 134


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


def p_tokens(d, y, css):
    tk, goal = d["tokens"], d["prof"]["goal_billions"] * 1e9
    since = datetime.date.fromisoformat(tk["since"])
    total = tk["total"]
    frac = min(1, total / goal) if goal else 0
    pct = f"{total / goal * 100:.1f}%" if goal else "0.0%"
    iw = W - 2 * M
    out = [title(M, y + 20, "Token spend", f"since {since:%b %Y}", W - M), disp(M, y + 76, n(total), fit(n(total), 56, 520)),
           disp(W - M, y + 66, pct, 44, WHITE, "end"), text(W - M, y + 88, f"of the {d['prof']['goal_billions']:g}B goal", 16, SEC, "end")]
    by = y + 100
    fw = max(12, round(iw * frac)) if frac else 0
    out.append(f'<rect x="{M}" y="{by}" width="{iw}" height="12" rx="6" fill="{TRACK}"/>')
    if fw:
        out += [f'<clipPath id="fc"><rect x="{M}" y="{by}" width="{fw}" height="12" rx="6"/></clipPath>',
                f'<rect class="fill" x="{M}" y="{by}" width="{fw}" height="12" rx="6" fill="{WHITE}"/>',
                f'<g clip-path="url(#fc)"><rect class="sweep" x="{M - SPAN}" y="{by}" width="{SPAN}" height="12" fill="url(#sw)"/></g>']
        css.append("@keyframes sweep{0%%{transform:translateX(0)}100%%{transform:translateX(%dpx)}}" % (fw + SPAN))
    models = tk.get("models") or {}
    sh = shares(models)
    if sh:
        sy, x = by + 24, M
        for i, (k, v) in enumerate(models.items()):
            w = max(6, (iw - 4 * (len(models) - 1)) * v / total)
            out.append(f'<rect x="{x:.1f}" y="{sy}" width="{w:.1f}" height="5" rx="2.5" fill="{SEG[min(i, 3)]}"/>')
            x += w + 4
        labels = "".join(f'<tspan dx="{0 if i == 0 else 28}">{escape(k)} {sh[k]}%</tspan>' for i, k in enumerate(models))
        out.append(f'<text x="{M}" y="{sy + 26}" font-family="{SANS}" font-size="16" fill="{SEC}">{labels}</text>')
    return out, 154


def p_contrib(d, y):
    """Left: 31-day bars with the 7-day average. Right: totals and streaks."""
    vals, ma, dates = d["last31"], d["ma"], d["dates"]
    mx = max(vals + [1])
    ch, base = 70, y + 118
    peak = vals.index(max(vals)) if max(vals) > 0 else None
    pitch = LEFT_W / 31
    out = [title(M, y + 20, "Contributions", f"{n(sum(vals))} in 31 days", M + LEFT_W)]
    for i, v in enumerate(vals):
        x = M + i * pitch + (pitch - 6) / 2
        if v == 0:
            out.append(f'<rect x="{x:.1f}" y="{base - 2}" width="6" height="2" rx="1" fill="{EMPTY}"/>')
        else:
            bh = max(5, round(ch * v / mx))
            out.append(f'<rect class="bar" x="{x:.1f}" y="{base - bh}" width="6" height="{bh}" rx="3" '
                       f'fill="{RED if i == peak else BAR}" style="animation-delay:{i * 0.08:.2f}s"/>')
    if peak is not None:
        out.append(text(M + peak * pitch + pitch / 2, base - round(ch * vals[peak] / mx) - 8, str(vals[peak]), 16, WHITE, "middle", "700"))
    pts = " ".join(f"{M + i * pitch + pitch / 2:.1f},{base - ch * m / mx:.1f}" for i, m in enumerate(ma))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{WHITE}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    out.append(f'<line x1="{M}" y1="{base + 28}" x2="{M + 24}" y2="{base + 28}" stroke="{WHITE}" stroke-width="2" stroke-linecap="round"/>'
               + text(M + 34, base + 33, "7-day average", 16, SEC)
               + text(M + LEFT_W, base + 33, f"{dates[0]:%b} {dates[0].day} to {dates[-1]:%b} {dates[-1].day}", 16, SEC, "end"))
    out.append(title(RX, y + 20, "Totals", "all time", W - M))
    rows = [(n(d["total"]), "contributions", WHITE), (str(d["cur"]), "day streak", RED if d["cur"] else WHITE),
            (str(d["best"]), "best streak", WHITE)]
    for i, (v, lab, col) in enumerate(rows):
        size = fit(v, 32, 130)
        out += [disp(RX, y + 66 + i * 38, v, size, col), text(RX + len(v) * size * 0.6 + 12, y + 66 + i * 38, lab, 16, SEC)]
    return out, 158


def p_langs_stack(d, y):
    """Left: top languages by bytes. Right: tool icons in a small grid."""
    langs = sorted(d["langs"].items(), key=lambda kv: -kv[1])[:5]
    tot = sum(d["langs"].values())
    out = [title(M, y + 20, "Languages", "by bytes", M + LEFT_W)]
    lang_h = 40
    if not langs or not tot:
        out.append(text(M, y + 58, "No language data", 18, SEC))
    else:
        bx, bw = M + 150, 280
        for i, (name, b) in enumerate(langs):
            ry, pct = y + 38 + i * 26, b / tot
            out += [text(M, ry + 14, clip(name, 14), 18), f'<rect x="{bx}" y="{ry + 4}" width="{bw}" height="10" rx="5" fill="{TRACK}"/>',
                    f'<rect x="{bx}" y="{ry + 4}" width="{max(10, round(bw * pct))}" height="10" rx="5" fill="{WHITE if i == 0 else BAR}"/>',
                    text(M + LEFT_W, ry + 14, f"{pct * 100:.1f}%", 18, WHITE, "end")]
        lang_h = 38 + len(langs) * 26
    tools = d["tools"]
    out.append(title(RX, y + 20, "Stack", f"{len(tools)} tools", W - M))
    for i, t in enumerate(tools):
        out.append(f'<g transform="translate({RX + (i % 4) * 64} {y + 42 + (i // 4) * 44}) scale(1.5)">'
                   f'<title>{escape(t["name"])}</title><path d="{d["icons"][t["icon"]]}" fill="{WHITE}"/></g>')
    stack_h = 42 + max(1, -(-len(tools) // 4)) * 44 - 8
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
    foot = y - GAP + 32
    parts.append(text(M, foot, f"Updated {et_label(d['now'])}", 16, SEC))
    height = foot + 16
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
