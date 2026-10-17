"""python tests/test_card.py [--previews] : edge cases for scripts/build_card.py, no network.
--previews also writes the edge-case SVGs to qc/ for rendering."""
import datetime, json, pathlib, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_card as b
import qc_card

NOW = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=datetime.timezone.utc)
PREVIEWS = "--previews" in sys.argv


def cal(counts):  # counts: {date: n}
    return [{"weeks": [{"contributionDays": [{"date": k, "contributionCount": v} for k, v in counts.items()]}]}]


def data(counts, langs, tmp):
    t = pathlib.Path(tmp)
    (t / "contributions.json").write_text(json.dumps(cal(counts)))
    (t / "languages.json").write_text(json.dumps(langs))
    return b.gather(str(t), NOW)


def day(i):
    return str(NOW.date() - datetime.timedelta(days=i))


def verify(name, d, tmp, max_height=qc_card.MAX_HEIGHT):
    """Build, run the readability/contrast rules on it, optionally keep it for rendering."""
    svg = b.build(d)
    p = pathlib.Path(tmp) / f"{name}.svg"
    p.write_text(svg, encoding="utf-8")
    _, _, _, fails = qc_card.check(p, max_height)
    assert not fails, (name, fails)
    if PREVIEWS:
        (ROOT / "qc").mkdir(exist_ok=True)
        (ROOT / "qc" / f"edge-{name}.svg").write_text(svg, encoding="utf-8")
    return svg


with tempfile.TemporaryDirectory() as tmp:
    # streak maths
    assert b.streaks({day(2): 1, day(1): 1, day(0): 1}, NOW.date()) == (3, 3)
    assert b.streaks({day(3): 1, day(2): 1, day(1): 1, day(0): 0}, NOW.date()) == (3, 3)  # today still 0: count from yesterday
    assert b.streaks({day(5): 1, day(4): 1, day(3): 1, day(1): 0, day(0): 0}, NOW.date()) == (0, 3)
    # moving average: full window, and partial windows when the calendar starts late
    days = {day(i): i % 5 for i in range(40)}
    dates = [NOW.date() - datetime.timedelta(days=i) for i in range(30, -1, -1)]
    assert abs(b.ma7(days, dates)[-1] - sum(days[day(k)] for k in range(7)) / 7) < 1e-9
    assert b.ma7({day(0): 7}, dates)[-1] == 7.0 and b.ma7({}, dates)[0] == 0.0
    # percentages always add up to 100
    assert sum(b.shares({"A": 1, "B": 1, "C": 1}).values()) == 100 and b.shares({}) == {}
    assert sum(b.shares({"Opus": 279, "Sonnet": 201, "Fable": 194, "Other": 180}).values()) == 100
    # US Eastern label and day boundary: 01:58 UTC on Oct 17 is still Oct 16 in New York
    assert b.et_label(datetime.datetime(2026, 10, 17, 1, 58, tzinfo=datetime.timezone.utc)) == "Oct 16, 9:58 PM ET"
    assert b.et_label(datetime.datetime(2026, 1, 15, 17, 5, tzinfo=datetime.timezone.utc)) == "Jan 15, 12:05 PM ET"
    late = datetime.datetime(2026, 10, 17, 1, 58, tzinfo=datetime.timezone.utc)
    t = pathlib.Path(tmp)
    (t / "contributions.json").write_text(json.dumps(cal({"2026-10-16": 4, "2026-10-15": 2})))
    (t / "languages.json").write_text("{}")
    g = b.gather(str(t), late)
    assert g["dates"][-1] == datetime.date(2026, 10, 16) and g["last31"][-1] == 4 and g["cur"] == 2
    # zero states: 0 streak, no languages, zero-activity days, no per-model data
    d = data({day(i): 0 for i in range(40)}, {}, tmp)
    d["tokens"] = {"total": 0, "claude": 0, "codex": 0, "since": "2026-06-26", "models": {}}
    svg = verify("zero", d, tmp)
    assert d["cur"] == 0 and d["best"] == 0 and "No language data" in svg and "of 10B" in svg
    # long token number, long name, hostile text, many stack items, a lone active day
    d = data({day(0): 5}, {"Python": 10, "A very long language name": 5}, tmp)
    d["tokens"] = {"total": 12_345_678_901, "claude": 12_345_678_901, "codex": 0, "since": "2026-06-26",
                   "models": {"Opus": 6_000_000_000, "Sonnet": 5_000_000_000, "Fable": 1_000_000_000, "Other": 345_678_901}}
    d["prof"] = dict(d["prof"], name="Pneu & <Co> Extraordinarily Long Display Name", tagline='say "hi" & <go>')
    d["tools"] = d["tools"] * 4
    svg = verify("long", d, tmp, max_height=None)  # 48 stack icons make this one legitimately tall
    assert "12,345,678,901" in svg and "123.5%" in svg
    # current streak colour: red only while the streak is active
    d = data({day(1): 2, day(0): 3}, {"Python": 1}, tmp)
    assert d["cur"] == 2
    live = b.build(d)
    d = data({day(0): 0}, {"Python": 1}, tmp)
    assert d["cur"] == 0 and b.build(d).count("#FF6F61") < live.count("#FF6F61")


# ---- model rows, goal and language bars: fill length is exactly pct/100 of the track
import re
import xml.etree.ElementTree as ET
import scan_tokens as sc
NS = "{http://www.w3.org/2000/svg}"


def extent(el):
    """(start, end) x of a bar element: rect attributes, or the path's extreme points plus the cap radius."""
    if el.tag == NS + "rect":
        return float(el.get("x")), float(el.get("x")) + float(el.get("width"))
    d = el.get("d")
    xs = [float(m.group(1)) for m in re.finditer(r"(-?\d+\.?\d*) -?\d+\.?\d*", re.sub(r"A\d+\.?\d* \d+\.?\d* 0 0 1", "", d))]
    r = float(re.search(r"A(\d+\.?\d*)", d).group(1))
    return min(xs) - r, max(xs) + r


def ys(el):
    if el.tag == NS + "rect":
        return [float(el.get("y")), float(el.get("y")) + float(el.get("height"))]
    d = re.sub(r"A\d+\.?\d* \d+\.?\d* 0 0 1", "", el.get("d"))
    return [float(m.group(1)) for m in re.finditer(r"-?\d+\.?\d* (-?\d+\.?\d*)", d)]


def fills(root):
    return [e for e in root.iter() if e.get("class") == "fil"]


CASES = {
    "one family at 100%": {"Opus": 5_000},
    "two families": {"Opus": 700, "Sonnet": 300},
    "four families": {"Opus": 400, "Sonnet": 300, "Fable": 200, "Haiku": 100},
    "six families": {"Opus": 300, "Sonnet": 250, "Fable": 200, "Haiku": 150, "Codex": 60, "Gemini": 40},
    "small families fold into Other": {"Opus": 900, "Sonnet": 60, "Fable": 20, "Haiku": 20},
    "Other under 2% is not drawn": {"Opus": 600, "Sonnet": 395, "Other": 5},
}
with tempfile.TemporaryDirectory() as tmp:
    for name, models in CASES.items():
        d = data({day(0): 1}, {"Python": 1}, tmp)
        d["tokens"] = {"total": sum(models.values()), "claude": 0, "codex": 0, "since": "2026-06-26", "models": models}
        svg = b.build(d)
        root = ET.fromstring(svg)
        segs = b.model_segments(models)
        pct = b.shares(dict(segs), 1000)
        assert sum(pct.values()) == 1000, name                                     # shares sum to 100.0%
        rows = [e for e in fills(root) if e.get("data-label") in [k for k, _ in segs]]
        assert [e.get("data-label") for e in rows] == [k for k, _ in segs], (name, "row order/names")
        named = [k for k, _ in segs if k != "Other"]
        assert named == sorted(named, key=lambda k: -dict(segs)[k]) and len(named) <= 4, name
        assert all(v / sum(models.values()) >= 0.03 for k, v in segs if k != "Other"), name
        for e, (k, v) in zip(rows, segs):
            t0, t1 = float(e.get("data-t0")), float(e.get("data-t1"))
            a, z = extent(e)
            assert abs(a - t0) < 0.01 and abs((z - a) - (t1 - t0) * pct[k] / 1000) < 0.01, (name, k, z - a)   # fill == pct of the track
        assert f"{pct[segs[0][0]] / 10:.1f}%" in svg, name
        p = pathlib.Path(tmp) / "x.svg"
        p.write_text(svg, encoding="utf-8")
        assert not qc_card.check(p, None)[3], name
    # goal bar and language bars use the same exact rule
    d = data({day(0): 1}, {"Python": 30, "Go": 12, "C": 1}, tmp)
    root = ET.fromstring(b.build(d))
    for e in fills(root):
        t0, t1, pc = float(e.get("data-t0")), float(e.get("data-t1")), float(e.get("data-pct"))
        a, z = extent(e)
        assert abs(a - t0) < 0.01 and abs((z - a) - (t1 - t0) * min(pc, 100) / 100) < 0.01, (e.get("data-label"), z - a)
    assert {e.get("data-label") for e in fills(root)} >= {"goal", "Python", "Go", "C"}

    # ---- scanner: usage shape in ET, same dedupe input
    now = datetime.datetime(2026, 10, 17, 2, 0, tzinfo=datetime.timezone.utc)        # Oct 16, 10pm ET
    sh = sc.usage_shape([("2026-10-17T01:30:00Z", 100), ("2026-10-16T14:00:00Z", 50), ("2026-09-10T12:00:00Z", 7), ("bad", 1)], now)
    assert sh["today"] == "2026-10-16" and len(sh["days"]) == 14 and sh["days"][-1] == {"date": "2026-10-16", "tokens": 150}
    assert sh["hours"][21] == 1 and sh["hours"][10] == 1 and sum(sh["hours"]) == 2   # 9:30pm and 10am ET; Sep 10 is outside 30 days
    assert sh["weekdays"][4] == 2 and sum(sh["weekdays"]) == 2                         # both Fridays in ET

    # ---- panels: heights, average line, dim/hollow, peaks, letters, against the JSON
    def shape(daily, hours, wk, today="2026-10-16"):
        t = datetime.date.fromisoformat(today)
        return {"today": today, "days": [{"date": str(t - datetime.timedelta(days=13 - i)), "tokens": v} for i, v in enumerate(daily)],
                "hours": hours, "weekdays": wk}

    SAMPLES = {
        "zero days": shape([0, 0, 500, 900, 0, 120, 1000, 0, 0, 400, 800, 0, 300, 1000], [0] * 8 + [3, 9, 4, 0, 0, 0, 0, 0, 0, 0, 0, 12, 2, 1, 0, 0], [5, 9, 4, 8, 7, 0, 3]),
        "ties": shape([100, 100, 40, 100, 40, 100, 100, 100, 100, 100, 100, 100, 100, 100], [5] * 24, [7, 7, 7, 7, 7, 7, 7]),
        "single-day spike": shape([0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 90_000, 0, 0], [0] * 20 + [8, 0, 0, 0], [0, 0, 0, 0, 40, 0, 0]),
        "all zero": shape([0] * 14, [0] * 24, [0] * 7),
    }
    for name, sh in SAMPLES.items():
        d = data({day(0): 1}, {"Python": 1}, tmp)
        d["shape"] = sh
        svg = b.build(d)
        root = ET.fromstring(svg)
        vals = [x["tokens"] for x in sh["days"]]
        mx, avg = max(vals), sum(vals) / 14
        bars = [e for e in root.iter() if e.get("class") == "dbar"]
        nz = [(i, v) for i, v in enumerate(vals) if v]
        stubs = [e for e in root.iter() if e.get("class") == "stub"]
        wk = sh["weekdays"]
        assert len(bars) == len(nz), name
        assert len(stubs) == (14 - len(nz)) + sum(1 for v in wk if v == 0 or max(wk) == 0), name   # hollow stubs: zero days and zero weekdays
        base = float(bars[0].get("data-base")) if bars else None
        peak = vals.index(mx) if mx else None                                        # ties: the first of the maxima
        for e, (i, v) in zip(bars, nz):
            h = max(1.5, b.HM * v / mx)
            y = ys(e)
            assert abs(min(y) - (base - h)) < 0.01 and abs(max(y) - base) < 0.01 and abs(float(e.get("data-h")) - h) < 0.01, (name, i)
            want = b.RED if i == peak else (b.DIM if v < 0.5 * avg else b.INK)
            assert e.get("fill") == want, (name, i, e.get("fill"), want)
        line = [e for e in root.iter() if e.get("class") == "avg"][0]
        assert abs(float(line.get("data-avg")) - avg) < 0.001
        texts = list(root.iter(NS + "text"))
        if mx:
            assert abs(float(line.get("y1")) - (base - b.HM * avg / mx)) < 0.01, name
            assert sum(1 for e in bars if e.get("fill") == b.RED) == 1, name
            assert f"avg {b.short(avg)}" in [t.text for t in texts], name             # the average line carries its value
            letters = [t.text for t in texts if abs(float(t.get("y")) - (base + b.LET_DY)) < 0.01 and len(t.text or "") == 1]
            assert "".join(letters) == "".join("MTWTFSS"[datetime.date.fromisoformat(x["date"]).weekday()] for x in sh["days"]), (name, letters)
        else:
            pass
        # time of day: peak cell red, label from data
        hrs = sh["hours"]
        reds = []
        if max(hrs):
            hp = hrs.index(max(hrs))
            cells = {int(e.get("data-h")): e.get("fill") for e in root.iter() if e.get("class") == "cell"}
            assert cells[hp] == b.INK and b.RED not in cells.values(), name         # peak hour is the brightest cell, no red
            assert f"peak {hp % 12 or 12}{'a' if hp < 12 else 'p'}" in [t.text for t in texts], name
        else:
            assert not reds and not [t.text for t in texts if (t.text or "").startswith("peak ")], name
        # weekday bars: heights, best brightest, weakest dimmer
        for e in [e for e in root.iter() if e.get("class") == "wbar"]:
            v, h = int(e.get("data-v")), float(e.get("data-h"))
            assert abs(h - max(1.5, b.WH * v / max(wk))) < 0.01 and abs((max(ys(e)) - min(ys(e))) - h) < 0.01, name
            if v == min(wk) and max(wk) != min(wk):
                assert e.get("fill") == b.DIM, name
        best = [e for e in root.iter() if e.get("class") == "wbar" and e.get("fill") == b.INK]
        assert (not max(wk) and not best) or (len(best) == 1 and int(best[0].get("data-v")) == max(wk)), name
        p = pathlib.Path(tmp) / "s.svg"
        p.write_text(svg, encoding="utf-8")
        assert not qc_card.check(p, None)[3], name
        if PREVIEWS:
            (ROOT / "qc" / f"shape-{name.replace(' ', '-')}.svg").write_text(svg, encoding="utf-8")

    # ---- handwritten notes: "on a run" only for streaks of 3 or more; wobble is deterministic
    d = data({day(2): 1, day(1): 1, day(0): 1}, {"Python": 1}, tmp)
    assert d["cur"] == 3 and "on a run" in b.build(d)
    d = data({day(1): 1, day(0): 0}, {"Python": 1}, tmp)
    assert d["cur"] == 1 and "on a run" not in b.build(d)
    d1, d2 = data({day(0): 5}, {"Python": 1}, tmp), data({day(0): 5}, {"Python": 1}, tmp)
    assert b.build(d1) == b.build(d2)                                                  # byte-identical rebuilds
    assert b.wob(1, 2, 3) == b.wob(1, 2, 3) and abs(b.wob(7)) <= 1

# ---- polish: value labels, removed text, one continuous banner path, spacing groups
with tempfile.TemporaryDirectory() as tmp:
    assert [b.short(v) for v in (0, 5, 950, 1_200, 48_000_000, 1_234_000_000, 6_278_959, 9_960_000, 999_700_000, 12_300_000_000)] ==         ["0", "5", "950", "1.2K", "48M", "1.2B", "6.3M", "10M", "1.0B", "12B"]
    vals = [0, 6_278_959, 208_125_014, 0, 0, 6_596_181, 0, 0, 129_668_677, 192_071_521, 235_822_793, 6_373_315, 0, 75_839_768]
    d = data({day(0): 1}, {"Python": 1}, tmp)
    d["shape"] = shape(vals, [1] * 24, [1] * 7)
    root = ET.fromstring(b.build(d))
    texts = [t.text for t in root.iter(NS + "text")]
    for gone in ("hollow = no usage", "best day", "peak", "avg"):
        assert gone not in texts, gone                                                   # standalone labels are gone
    assert any((t or "").startswith("avg ") for t in texts) and "breathe" in texts
    labels = {int(t.get("data-day")): (t.text, t.get("fill"), float(t.get("x")), float(t.get("y"))) for t in root.iter(NS + "text") if t.get("data-day")}
    mx = max(vals)
    assert labels[10][0] == "236M" and labels[10][1] == b.RED and labels[13][0] == "76M"      # peak (red) and today always labelled
    assert all(vals[i] and labels[i][0] == b.short(vals[i]) for i in labels) and not any(vals[i] == 0 for i in labels)
    boxes = [(x - b.label_w(t) / 2, x + b.label_w(t) / 2, y - 16, y + 5) for t, _, x, y in labels.values()]
    for i, A in enumerate(boxes):
        for B in boxes[i + 1:]:
            assert A[1] + 3 <= B[0] or B[1] + 3 <= A[0] or A[3] + 1 <= B[2] or B[3] + 1 <= A[2], "labels overlap"
    # crowded: neighbours collide, small bars (<15% of the max) lose their label, peak and today keep theirs
    xs = [100 + 20 * i for i in range(6)]
    got = b.daily_labels([1000, 900, 5, 800, 3, 4], xs, {i: 100 for i in range(6)}, 0, 5)
    assert set(got) == {0, 3, 5}, set(got)        # <15% bars (2, 4) skipped, then 900 dropped next to the peak; peak and today kept
    # banner: one path, left centre -> right centre, dot at the arc-length midpoint region; keyframes use the computed arrival
    d = data({day(0): 1}, {"Python": 1}, tmp)
    svg = b.build(d)
    root = ET.fromstring(svg)
    paths = [e for e in root.iter(NS + "path") if e.get("class") in ("base", "pulse", "tail")]
    assert len(paths) == 3 and len({e.get("d") for e in paths}) == 1 and paths[0].get("d").count("M") == 1
    g = b.banner_geometry({**d, "logo": b.read("logo.json")}, 0)
    assert 0.3 < g["l_dot"] / g["total"] < 0.7 and g["samples"][0][0] < 300 and g["samples"][-1][0] > 580 and g["samples"][0][0] < g["dot"][0] < g["samples"][-1][0]
    css = ET.fromstring(svg).find(NS + "style").text
    tm = b.breath_timing(g)
    assert abs(tm["t_in"] + tm["t_out"] - 6.0) < 1e-9 and tm["hold"] == 1.0 and b.CYCLE == 8.0   # inhale + exhale keep their 6s; 1s hold; 1s rest
    ti = tm["t_in"]
    assert b.head_at(g, 0) == 0 and b.head_at(g, ti - 0.01) < g["l_dot"] < b.head_at(g, ti + 1.01)
    assert all(abs(b.head_at(g, ti + k / 4) - g["l_dot"]) < 1e-9 for k in range(5))                # the pulse sits on the dot for exactly 1s
    speed = lambda t: abs(b.head_at(g, t + 0.001) - b.head_at(g, t)) / 0.001
    assert speed(ti - 0.002) < 0.02 * speed(ti / 2) and speed(ti + 1.0) < 0.02 * speed(ti + 1.0 + tm["t_out"] / 2) and speed(0) < 0.02 * speed(ti / 2)   # eased: no jump
    assert abs(b.head_at(g, ti + 1.0 + tm["t_out"]) - g["total"] * 1.18) < 1e-6 and b.head_at(g, b.CYCLE) == b.head_at(g, ti + 1.0 + tm["t_out"])
    pc = lambda t: f"{t / b.CYCLE * 100:.3f}%"
    offs = re.search(r"@keyframes poff\{(.*?)\}\}?@keyframes", css).group(1)
    got = dict(re.findall(r"([\d.]+%)\{stroke-dashoffset:(-?[\d.]+)\}", offs))
    assert got[pc(ti)] == got[pc(ti + 1.0)], (got[pc(ti)], got[pc(ti + 1.0)])                       # identical dashoffset at both ends of the hold
    assert f"{pc(ti)}{{stroke-opacity:1}}{pc(ti + 1.0)}{{stroke-opacity:1}}" in css and " 8s " in css and "prefers-reduced-motion" in css
    # groups for the spacing QC exist
    ids = {e.get("id") for e in root.iter(NS + "g") if e.get("id")}
    assert {"sec-banner", "sec-tokens", "sec-daily", "sec-tod", "sec-weekday", "sec-activity", "sec-streak", "sec-langs", "sec-stack", "sec-footer"} <= ids
print("all edge-case checks passed")
