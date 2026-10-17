"""python tests/test_card.py : edge cases for scripts/build_card.py, no network."""
import datetime, json, pathlib, sys, tempfile, xml.dom.minidom
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import build_card as b

NOW = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=datetime.timezone.utc)


def cal(counts):  # counts: {date: n}
    return [{"weeks": [{"contributionDays": [{"date": k, "contributionCount": v} for k, v in counts.items()]}]}]


def data(counts, langs, tmp):
    t = pathlib.Path(tmp)
    (t / "contributions.json").write_text(json.dumps(cal(counts)))
    (t / "languages.json").write_text(json.dumps(langs))
    return b.gather(str(t), NOW)


def ok(svg):
    xml.dom.minidom.parseString(svg)
    assert "<script" not in svg and "http://" not in svg.replace("http://www.w3.org/2000/svg", "") and "href" not in svg
    assert len(svg.encode()) < 1_000_000


def day(i):
    return str(NOW.date() - datetime.timedelta(days=i))


with tempfile.TemporaryDirectory() as tmp:
    # streak maths
    assert b.streaks({day(2): 1, day(1): 1, day(0): 1}, NOW.date()) == (3, 3)
    assert b.streaks({day(3): 1, day(2): 1, day(1): 1, day(0): 0}, NOW.date()) == (3, 3)  # today still 0: count from yesterday
    assert b.streaks({day(5): 1, day(4): 1, day(3): 1, day(1): 0, day(0): 0}, NOW.date()) == (0, 3)
    # 0 streak, no languages
    d = data({day(i): 0 for i in range(40)}, {}, tmp)
    svg = b.build(d)
    ok(svg)
    assert d["cur"] == 0 and d["best"] == 0 and "No language data" in svg and "0/0" in svg
    # long site name, long name, many stack items, XML-hostile text
    d = data({day(0): 5}, {"Python": 10}, tmp)
    assert d["sites"] == [] and "Shipped" not in b.build(d) and "live site" not in b.build(d)  # no sites.json: no Shipped panel
    d["sites"] = [{"site": "a-very-long-site-name-that-keeps-going.example.com", "kind": "x" * 60}] * 9
    d["prof"] = dict(d["prof"], name="Pneu & <Co> Extraordinarily Long Display Name", tagline='say "hi" & <go>')
    d["tools"] = d["tools"] * 4
    svg = b.build(d)
    ok(svg)
    assert "a-very-long-site-name-that-keeps-going.example.com" not in svg and "…" in svg and "SHIPPED" in svg
    assert "f5a524" not in svg and "#fff" in svg.lower()  # monochrome, no amber
print("all edge-case checks passed")
