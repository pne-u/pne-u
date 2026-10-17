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


# ---- model bar: segment widths equal shares, labels sit under their own segment, no overlaps
import xml.etree.ElementTree as ET
NS = "{http://www.w3.org/2000/svg}"
CASES = {
    "one family at 100%": {"Opus": 5_000},
    "two families": {"Opus": 700, "Sonnet": 300},
    "four families": {"Opus": 400, "Sonnet": 300, "Fable": 200, "Haiku": 100},
    "six families": {"Opus": 300, "Sonnet": 250, "Fable": 200, "Haiku": 150, "Codex": 60, "Gemini": 40},
    "small families fold into Other": {"Opus": 900, "Sonnet": 60, "Fable": 20, "Haiku": 20},
    "Other under 2% is not drawn": {"Opus": 600, "Sonnet": 395, "Other": 5},
    "tiny segments stagger labels": {"Opus": 880, "Sonnet": 40, "Fable": 35, "Haiku": 25, "Other": 20},
}
with tempfile.TemporaryDirectory() as tmp:
    for name, models in CASES.items():
        d = data({day(0): 1}, {"Python": 1}, tmp)
        d["tokens"] = {"total": sum(models.values()), "claude": 0, "codex": 0, "since": "2026-06-26", "models": models}
        svg = b.build(d)
        root = ET.fromstring(svg)
        segs = b.model_segments(models)
        names = [k for k, _ in segs]
        rects = [r for r in root.iter(NS + "rect") if r.get("class") == "mseg"]
        assert [r.get("data-name") for r in rects] == names, (name, names)
        assert all(r.get("height") == "20" for r in rects) and len(rects) <= 5
        avail = b.IW - 2 * (len(rects) - 1)
        drawn = sum(v for _, v in segs)
        for r, (k, v) in zip(rects, segs):
            assert abs(float(r.get("width")) - avail * v / drawn) < 0.01, (name, k)          # width == share
        pcts = b.shares(dict(segs))
        assert sum(pcts.values()) == 100, name
        assert names == sorted(names[:-1] if names[-1] == "Other" else names, key=lambda k: -dict(segs)[k]) + (["Other"] if names[-1] == "Other" else []), name
        assert all(v / sum(models.values()) >= 0.03 for k, v in segs if k != "Other"), name  # nothing under 3% is drawn
        # labels: left-aligned at their own segment, same row never overlap
        labels = {t.text: (float(t.get("x")), float(t.get("y")), t.get("text-anchor")) for t in root.iter(NS + "text")}
        placed = []
        for r, (k, v) in zip(rects, segs):
            lab = f"{k} {pcts[k]}%"
            x, y, anchor = labels[lab]
            if anchor == "start":
                assert abs(x - float(r.get("x"))) < 0.01, (name, lab)  # sits at its own segment start
            else:  # only a segment starting too far right may right-align; the label must still sit under it
                seg_lo, seg_hi = float(r.get("x")), float(r.get("x")) + float(r.get("width"))
                assert x - len(lab) * b.LABEL_W <= seg_hi and x >= seg_lo, (name, lab)
            lo = x if anchor == "start" else x - len(lab) * b.LABEL_W
            placed.append((y, lo, lo + len(lab) * b.LABEL_W))
        for i, (y1, a1, b1) in enumerate(placed):
            for y2, a2, b2 in placed[i + 1:]:
                assert y1 != y2 or b1 + 4 <= a2 or b2 + 4 <= a1, (name, "labels overlap")
        _, _, _, fails = qc_card.check(pathlib.Path(tmp) / "x.svg", None) if (pathlib.Path(tmp) / "x.svg").write_text(svg, encoding="utf-8") else (0, 0, 0, [])
        assert not fails, (name, fails)
    assert b.model_segments({}) == [] and b.model_segments({"Other": 0}) == []
print("all edge-case checks passed")
