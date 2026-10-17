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
    # US Eastern label: EDT in October, EST in January
    assert b.et_label(datetime.datetime(2026, 10, 17, 1, 58, tzinfo=datetime.timezone.utc)) == "Oct 16, 9:58 PM EDT"
    assert b.et_label(datetime.datetime(2026, 1, 15, 17, 5, tzinfo=datetime.timezone.utc)) == "Jan 15, 12:05 PM EST"
    # zero states: 0 streak, no languages, zero-activity days, no per-model data
    d = data({day(i): 0 for i in range(40)}, {}, tmp)
    d["tokens"] = {"total": 0, "claude": 0, "codex": 0, "since": "2026-06-26", "models": {}}
    svg = verify("zero", d, tmp)
    assert d["cur"] == 0 and d["best"] == 0 and "No language data" in svg and "of the 10B goal" in svg
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
print("all edge-case checks passed")
