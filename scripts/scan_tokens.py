#!/usr/bin/env python3
"""Sum token usage from local Claude Code logs (plus ~/.codex/sessions if that folder exists) into data/tokens.json.

  python scripts/scan_tokens.py          write data/tokens.json
  python scripts/scan_tokens.py --push   also pull --rebase, commit if changed, push (retry once); errors go to logs/token-sync.log
Only aggregates are written; "since" is the earliest log timestamp found.
"""
import datetime, glob, json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOME = os.path.expanduser("~")
TOKENS = ROOT / "data" / "tokens.json"
LOG = ROOT / "logs" / "token-sync.log"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now().astimezone():%Y-%m-%d %H:%M:%S%z} {msg}\n")


def jsonl(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                pass


def claude():
    seen, first = {}, "9999"  # streaming writes the same message repeatedly: one entry per message id + request id
    for p in glob.glob(os.path.join(HOME, ".claude", "projects", "**", "*.jsonl"), recursive=True):
        for d in jsonl(p):
            m = d.get("message")
            if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
                continue
            u, ts = m["usage"], (d.get("timestamp") or "")[:10]
            if ts:
                first = min(first, ts)
            seen[(m.get("id"), d.get("requestId"), d.get("uuid") if not m.get("id") else None)] = sum(
                u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
    return sum(seen.values()), first


def codex():
    total, first = 0, "9999"
    for p in glob.glob(os.path.join(HOME, ".codex", "sessions", "**", "*.jsonl"), recursive=True):
        last = 0  # token_count events are cumulative per session: keep the last
        for d in jsonl(p):
            ts = (d.get("timestamp") or "")[:10]
            if ts:
                first = min(first, ts)
            pl = d.get("payload") or {}
            if pl.get("type") == "token_count":
                last = ((pl.get("info") or {}).get("total_token_usage") or {}).get("total_tokens", last) or last
        total += last
    return total, first


def compute():
    c, c_first = claude()
    x, x_first = codex() if os.path.isdir(os.path.join(HOME, ".codex", "sessions")) else (0, "9999")
    return {"total": c + x, "claude": c, "codex": x, "since": min(c_first, x_first)}


def git(*args):
    done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8",
                          creationflags=NO_WINDOW, timeout=120)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.strip()


def write(out):
    new = json.dumps(out, indent=1) + "\n"
    if TOKENS.exists() and TOKENS.read_text(encoding="utf-8") == new:
        return False
    TOKENS.write_text(new, encoding="utf-8", newline="\n")
    return True


def sync():
    git("pull", "--rebase", "--autostash", "origin", "main")
    out = compute()
    if not write(out):
        log(f"unchanged total={out['total']}, no commit")
        return
    git("add", "data/tokens.json")
    git("commit", "-m", f"Update token totals ({out['total']:,})")
    git("push", "origin", "HEAD:main")
    log(f"pushed {git('rev-parse', '--short', 'HEAD')} total={out['total']}")


def main():
    if "--push" not in sys.argv:
        out = compute()
        write(out)
        print(out)
        return
    for attempt in (1, 2):
        try:
            return sync()
        except Exception as e:
            log(f"attempt {attempt} failed: {e}")
    sys.exit(1)


if __name__ == "__main__":
    main()
