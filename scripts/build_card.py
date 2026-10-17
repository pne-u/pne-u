#!/usr/bin/env python3
"""Draws assets/card.svg from data/*.json, the GitHub contribution calendar and language bytes.

  python scripts/build_card.py                 online: gh api (GH_TOKEN or a logged-in gh)
  python scripts/build_card.py --offline DIR   DIR/contributions.json + DIR/languages.json, no network
  python scripts/build_card.py --fetch-icons   cache simple-icons paths into data/icons.json

Stdlib only. The SVG has no scripts, no external requests, no web fonts: a monospace system stack and
inlined icon paths. It paints its own black background, so it reads the same in light and dark mode.
data/sites.json is optional: create it ([{"site": "...", "kind": "..."}]) to bring the Shipped panel back.
"""
import argparse, datetime, json, pathlib, subprocess, urllib.error, urllib.request
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parents[1]
W, PAD = 855, 26
BG, LINE, TEXT, MUTED, BAR = "#000000", "#2a2a2a", "#ffffff", "#8a8a8a", "#555555"
MONO = "ui-monospace,'SFMono-Regular',Consolas,Menlo,'Liberation Mono',monospace"
ICON_URL = "https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/{}.svg"
MAX_SITE = 24  # characters before a site name is cut with an ellipsis


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
    return {"prof": prof, "tools": tools, "sites": read("sites.json", []), "tokens": read("tokens.json"),
            "icons": icons, "langs": langs, "days": days, "last31": last31, "total": sum(days.values()),
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

def n(v):
    return f"{v:,}"


def clip(s, k):
    return s if len(s) <= k else s[:k - 1] + "…"


def text(x, y, s, size, fill=TEXT, anchor="start", weight="400", ls=0):
    extra = f' letter-spacing="{ls}"' if ls else ""
    return (f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra}>{escape(s)}</text>')


def label(x, y, title, sub=""):
    head = f"> {title.upper()}"
    out = text(x, y, head, 13, TEXT, weight="700", ls=1)
    if sub:
        out += text(x + len(head) * 9 + 12, y, "// " + sub.upper(), 10, MUTED, ls=1)
    return out


def hline(y):
    return f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="{LINE}"/>'


def vline(x, y1, y2):
    return f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{LINE}"/>'


def track(x, y, w, frac, h=8):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{LINE}"/>'
            f'<rect x="{x}" y="{y}" width="{max(h, round(w * frac)) if frac else 0}" height="{h}" rx="{h / 2}" fill="{TEXT}"/>')


def p_header(d, y):
    prof, now = d["prof"], d["now"]
    name = prof["name"].upper()
    size = int(min(64, 780 / (0.62 * max(len(name), 1))))
    return [text(PAD, y + 24, f"{prof['login']}@github:~$ card", 10, MUTED, ls=1),
            text(W - PAD, y + 24, f"UPDATED {now:%Y-%m-%d %H:%M} UTC", 10, MUTED, "end", ls=1),
            hline(y + 38),
            text(PAD, y + 38 + 78, name, size, TEXT, weight="700"),
            text(PAD, y + 38 + 104, "> " + prof["tagline"], 14, MUTED),
            hline(y + 38 + 124)], 38 + 124


def p_stack(d, y):
    tools, per_row = d["tools"], (W - 2 * PAD) // 48
    rows = max(1, -(-len(tools) // per_row))
    out = [label(PAD, y + 30, "Stack", f"{len(tools)} tools")]
    for i, t in enumerate(tools):
        cx, cy = PAD + (i % per_row) * 48, y + 50 + (i // per_row) * 46
        out.append(f'<g transform="translate({cx} {cy})"><title>{escape(t["name"])}</title>'
                   f'<path d="{d["icons"][t["icon"]]}" fill="{TEXT}"/></g>')
    h = 50 + rows * 46 + 8
    out.append(hline(y + h))
    return out, h


def p_contrib(d, y):
    """Left: 31-day bars. Right: totals and streaks."""
    h, split = 200, 570
    vals, mx = d["last31"], max(d["last31"] + [1])
    top3 = [i for i in sorted(range(31), key=lambda i: -vals[i])[:3] if vals[i]]
    out = [label(PAD, y + 30, "Contributions", f"{n(sum(vals))} in the last 31 days")]
    base, ch, bw = y + h - 34, 100, 13
    for i, v in enumerate(vals):
        bh = max(2, round(ch * v / mx)) if v else 2
        out.append(f'<rect x="{PAD + i * 17}" y="{base - bh}" width="{bw}" height="{bh}" rx="1.5" fill="{TEXT if i in top3 else BAR}"/>')
    if top3:
        i = top3[0]
        out.append(text(PAD + i * 17 + bw / 2, base - round(ch * vals[i] / mx) - 6, str(vals[i]), 10, TEXT, "middle"))
    first = d["now"].date() - datetime.timedelta(days=30)
    out += [text(PAD, y + h - 12, f"{first:%b %d}".upper(), 10, MUTED, ls=1),
            text(split - 30, y + h - 12, "TODAY", 10, MUTED, "end", ls=1)]
    x = split + 26
    big = lambda yy, v, size, note: text(x, yy, v, size, TEXT, weight="700") + text(x + len(v) * size * 0.6 + 12, yy, note, 11, MUTED)
    out += [vline(split, y, y + h), label(x, y + 30, "Totals", "all time"),
            big(y + 82, n(d["total"]), 40, "contributions"),
            big(y + 118, str(d["cur"]), 30, "day streak, current"),
            big(y + 150, str(d["best"]), 30, "day streak, best")]
    bw2 = W - PAD - x - 60
    out += [track(x, y + 168, bw2, min(1, d["cur"] / d["best"]) if d["best"] else 0),
            text(W - PAD, y + 177, f"{d['cur']}/{d['best']}", 10, MUTED, "end"), hline(y + h)]
    return out, h


def lang_rows(d, x, y, bar_w, right):
    langs = sorted(d["langs"].items(), key=lambda kv: -kv[1])[:6]
    tot = sum(d["langs"].values())
    if not langs or not tot:
        return [text(x, y + 20, "No language data", 13, MUTED)]
    out = []
    for i, (name, b) in enumerate(langs):
        ry, pct = y + i * 28, b / tot
        out += [text(x, ry + 10, clip(name, 14), 12), f'<rect x="{x + 130}" y="{ry}" width="{bar_w}" height="10" rx="5" fill="{LINE}"/>',
                f'<rect x="{x + 130}" y="{ry}" width="{max(4, round(bar_w * pct))}" height="10" rx="5" fill="{TEXT if i == 0 else BAR}"/>',
                text(right, ry + 10, f"{pct * 100:.1f}%", 11, MUTED, "end")]
    return out


def p_langs(d, y):
    """Languages across the full width, or beside the Shipped panel when data/sites.json lists sites."""
    sites = d["sites"]
    rows = max(1, min(6, len(d["langs"])))
    h = 232 if sites else 62 + rows * 28 + 8
    out = [label(PAD, y + 30, "Languages", "by bytes")]
    if not sites:
        out += lang_rows(d, PAD, y + 62, W - 2 * PAD - 130 - 70, W - PAD) + [hline(y + h)]
        return out, h
    split = 427
    out += lang_rows(d, PAD, y + 62, 180, split - 24)
    x = split + 26
    out += [vline(split, y, y + h), label(x, y + 30, "Shipped", "live sites"),
            text(x, y + 92, str(len(sites)), 52, TEXT, weight="700"),
            text(x + 70, y + 72, "live sites" if len(sites) != 1 else "live site", 12), text(x + 70, y + 88, "built by me, public today", 10, MUTED)]
    for i, s in enumerate(sites[:6]):
        ry = y + 118 + i * 17
        out += [f'<circle cx="{x + 3}" cy="{ry - 4}" r="2.5" fill="{TEXT}"/>', text(x + 14, ry, clip(s["site"], MAX_SITE), 11.5),
                text(W - PAD, ry, clip(s["kind"], 18), 10.5, MUTED, "end")]
    out.append(hline(y + h))
    return out, h


def p_tokens(d, y):
    h, tk, prof = 150, d["tokens"], d["prof"]
    since = datetime.date.fromisoformat(tk["since"])
    out = [label(PAD, y + 30, "Token spend", f"since {since:%b %Y}"),
           text(PAD, y + 88, n(tk["total"]), 52, TEXT, weight="700")]
    bw, goal = W - 2 * PAD - 80, prof["goal_billions"] * 1e9
    out += [track(PAD, y + 104, bw, min(1, tk["total"] / goal) if goal else 0, 10),
            text(W - PAD, y + 113, f"{tk['total'] / 1e9:.1f}B/{prof['goal_billions']:g}B", 11, MUTED, "end")]
    return out, h


def build(d):
    parts, y = [], 0
    for fn in (p_header, p_stack, p_contrib, p_langs, p_tokens):
        out, h = fn(d, y)
        parts += out
        y += h
    desc = (f"{d['prof']['name']} GitHub profile card: {len(d['tools'])} tools, {n(d['total'])} contributions, "
            f"{d['cur']} day streak, {n(d['tokens']['total'])} tokens" + (f", {len(d['sites'])} live sites." if d["sites"] else "."))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{y}" viewBox="0 0 {W} {y}" role="img" aria-label="{escape(desc)}">'
            f'<title>{escape(desc)}</title><rect width="{W}" height="{y}" rx="12" fill="{BG}"/>' + "".join(parts) +
            f'<rect x=".5" y=".5" width="{W - 1}" height="{y - 1}" rx="12" fill="none" stroke="{LINE}"/></svg>\n')


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
