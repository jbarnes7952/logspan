import json
import os
import subprocess
import sys

import pytest

import logspan

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def f(name):
    return os.path.join(FIX, name)


@pytest.mark.parametrize("name,start,end,dur,lines", [
    ("seastar.log", "2026-09-15 14:22:31.242", "2026-09-15 14:25:12.255", "2m 41s", 3),
    ("sidecar.json", "2026-09-14 00:01:45.414Z", "2026-09-15 14:22:45.987Z", "1d 14h 21m 0s", 2),
    ("access.log", "2026-09-15 14:22:31.000Z", "2026-09-15 14:23:31.000Z", "1m 0s", 2),
    ("epoch.log", "2026-09-10 00:26:40.123Z", "2026-09-10 00:27:40.000Z", "59s", 2),
])
def test_formats(name, start, end, dur, lines):
    r = logspan.span(f(name))
    assert r["status"] == "ok"
    assert r["start"] == start
    assert r["end"] == end
    assert r["duration"] == dur
    assert r["lines"] == lines


def test_syslog_uses_current_year():
    r = logspan.span(f("syslog.log"))
    assert r["status"] == "ok"
    assert r["duration"] == "1h 0m 0s"


def test_empty_and_no_dates_and_missing():
    assert logspan.span(f("empty.log"))["status"] == "empty"
    assert logspan.span(f("nodates.log"))["status"] == "no timestamp found"
    assert logspan.span(f("does-not-exist"))["status"] == "not found"


def test_unterminated_last_line_counted():
    assert logspan.span(f("epoch.log"))["lines"] == 2


def test_large_file_reads_only_ends(tmp_path):
    p = tmp_path / "big.log"
    with open(p, "w") as fh:
        fh.write("INFO  2026-01-01 00:00:00,000 first\n")
        fh.write(("x" * 200 + "\n") * 20000)          # ~4 MB of junk
        fh.write("INFO  2026-01-01 01:00:00,000 last\n")
    r = logspan.span(str(p))
    assert r["duration"] == "1h 0m 0s"
    assert r["lines"] == 20002
    assert r["size_bytes"] == os.path.getsize(p)


def test_fmt_size():
    assert logspan.fmt_size(0) == "0B"
    assert logspan.fmt_size(1023) == "1023B"
    assert logspan.fmt_size(1024) == "1.0K"
    assert logspan.fmt_size(10333319) == "9.9M"


def test_cli_json_and_table():
    out = subprocess.run([sys.executable, "-m", "logspan", "-j", f("seastar.log")],
                         capture_output=True, text=True, check=True).stdout
    row = json.loads(out.strip())
    assert row["duration_seconds"] == pytest.approx(161.013)
    out = subprocess.run([sys.executable, "-m", "logspan", FIX],
                         capture_output=True, text=True, check=True).stdout
    assert "(empty)" in out and "seastar.log" in out
    v = subprocess.run([sys.executable, "-m", "logspan", "--version"],
                       capture_output=True, text=True, check=True).stdout
    assert v.strip() == f"logspan {logspan.__version__}"


def test_skip_empty_flag():
    run = lambda *a: subprocess.run([sys.executable, "-m", "logspan", *a],
                                    capture_output=True, text=True).stdout
    assert "(empty)" in run(FIX)
    out = run("--skip-empty", FIX)
    assert "(empty)" not in out and "seastar.log" in out
    rows = [json.loads(l) for l in run("-j", "--skip-empty", FIX).splitlines()]
    assert rows and all(r["status"] != "empty" for r in rows)
    assert run("--skip-empty", f("empty.log")) == ""


def test_unknown_flag_is_an_error():
    r = subprocess.run([sys.executable, "-m", "logspan", "--bogus", FIX],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "unrecognized" in r.stderr


def test_recursive_and_display_names(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "top.log").write_text("INFO  2026-01-01 00:00:00,000 x\n")
    (tmp_path / "a" / "b" / "deep.log").write_text("INFO  2026-01-01 00:00:00,000 x\n")
    run = lambda *a: subprocess.run([sys.executable, "-m", "logspan", *a],
                                    capture_output=True, text=True, check=True).stdout
    flat = run(str(tmp_path))
    assert "top.log" in flat and "deep.log" not in flat
    rec = run("-r", str(tmp_path))
    assert os.path.join("a", "b", "deep.log") in rec
    assert str(tmp_path) not in rec
    full = run("-r", "--full-path", str(tmp_path))
    assert str(tmp_path / "a" / "b" / "deep.log") in full
    rows = [json.loads(l) for l in run("-j", "-r", str(tmp_path)).splitlines()]
    names = sorted(r["name"] for r in rows)
    assert names == sorted([os.path.join("a", "b", "deep.log"), "top.log"])
    assert all(os.path.isabs(r["file"]) for r in rows)


def test_glob_filter(tmp_path):
    (tmp_path / "sub").mkdir()
    for n in ("a.log", "b.txt", "c.json", "sub/d.log", "sub/e.yaml"):
        (tmp_path / n).write_text("INFO  2026-01-01 00:00:00,000 x\n")
    run = lambda *a: [json.loads(l) for l in subprocess.run(
        [sys.executable, "-m", "logspan", "-j", *a],
        capture_output=True, text=True, check=True).stdout.splitlines()]
    names = lambda rows: sorted(r["name"] for r in rows)
    assert names(run("-g", "*.log", str(tmp_path))) == ["a.log"]
    assert names(run("-r", "-g", "*.log", str(tmp_path))) == ["a.log", os.path.join("sub", "d.log")]
    assert names(run("-g", "*.log", "-g", "*.txt", str(tmp_path))) == ["a.log", "b.txt"]
    assert names(run("-g", "*.log,*.txt", str(tmp_path))) == ["a.log", "b.txt"]
    # explicit file arguments bypass the filter
    assert names(run("-g", "*.log", str(tmp_path / "c.json"))) == [str(tmp_path / "c.json")]
    assert run("-g", "*.nomatch", str(tmp_path)) == []


def test_completion_script_prints_and_matches_repo_copy():
    out = subprocess.run([sys.executable, "-m", "logspan", "--completion", "zsh"],
                         capture_output=True, text=True, check=True).stdout
    assert out.startswith("#compdef logspan")
    repo = os.path.join(os.path.dirname(__file__), "..", "completions", "_logspan")
    assert out == open(repo).read()
    # every long option the parser knows appears in the completion script
    for opt in ("--json", "--recursive", "--glob", "--skip-empty",
                "--full-path", "--completion", "--help", "--version"):
        assert opt in out, opt


def test_trailing_utc_token_is_a_zone(tmp_path):
    p = tmp_path / "pg.log"
    p.write_text("2026-09-11 14:00:00.000 UTC [1] LOG: a\n2026-09-11 15:00:00.000 GMT [1] LOG: b\n")
    r = logspan.span(str(p))
    assert r["start"] == "2026-09-11 14:00:00.000Z"
    assert r["end"] == "2026-09-11 15:00:00.000Z"
