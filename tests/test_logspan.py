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


def test_syslog_uses_mtime_year(tmp_path):
    import shutil, time
    p = tmp_path / "syslog.log"
    shutil.copy(f("syslog.log"), p)
    t = time.mktime((2023, 9, 15, 16, 0, 0, 0, 0, -1))
    os.utime(p, (t, t))
    r = logspan.span(str(p))
    assert r["status"] == "ok"
    assert r["duration"] == "1h 0m 0s"
    assert r["start"].startswith("2023-09-15 14:22:31")


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


def test_syslog_year_wrap_uses_mtime_year_for_end(tmp_path):
    import time
    p = tmp_path / "wrap.log"
    p.write_text("Dec 31 22:30:34 host a: x\nDec 31 23:59:59 host a: y\nJan 01 02:40:04 host a: z\n")
    jan2_2025 = time.mktime((2025, 1, 2, 12, 0, 0, 0, 0, -1))
    os.utime(p, (jan2_2025, jan2_2025))
    r = logspan.span(str(p))
    assert r["duration"] == "4h 9m 30s"
    assert r["duration_seconds"] == 4 * 3600 + 9 * 60 + 30
    assert r["year_assumed"] is True
    assert r["start"].startswith("2024-12-31 22:30:34")
    assert r["end"].startswith("2025-01-01 02:40:04")
    out = subprocess.run([sys.executable, "-m", "logspan", str(p)],
                         capture_output=True, text=True, check=True).stdout
    assert "(year assumed)" in out


def test_year_assumed_false_for_dated_formats():
    assert logspan.span(f("seastar.log"))["year_assumed"] is False
    assert logspan.span(f("syslog.log"))["year_assumed"] is True


def test_slash_date_format(tmp_path):
    p = tmp_path / "slash.log"
    p.write_text("2026/09/15 14:22:31.242 INFO a\n2026/09/15 15:22:31.242 INFO b\n")
    r = logspan.span(str(p))
    assert r["start"] == "2026-09-15 14:22:31.242"
    assert r["duration"] == "1h 0m 0s"
    assert r["year_assumed"] is False


def test_mixed_separator_is_rejected():
    assert logspan.parse_ts("2026-09/15 14:22:31 x") is None


def test_glog_format_uses_mtime_year(tmp_path):
    import time
    p = tmp_path / "kubelet.log"
    p.write_text("I0915 14:22:31.242000    1 main.go:12] start\n"
                 "W0915 14:30:00.000000    1 main.go:99] warn\n"
                 "E0915 16:22:31.242000  123 main.go:12] end\n")
    t = time.mktime((2025, 9, 15, 17, 0, 0, 0, 0, -1))
    os.utime(p, (t, t))
    r = logspan.span(str(p))
    assert r["start"] == "2025-09-15 14:22:31.242"
    assert r["end"] == "2025-09-15 16:22:31.242"
    assert r["duration"] == "2h 0m 0s"
    assert r["year_assumed"] is True


def test_glog_year_wrap(tmp_path):
    import time
    p = tmp_path / "etcd.log"
    p.write_text("I1231 23:50:00.000000 1 a.go:1] x\nI0101 00:10:00.000000 1 a.go:1] y\n")
    t = time.mktime((2025, 1, 1, 1, 0, 0, 0, 0, -1))
    os.utime(p, (t, t))
    r = logspan.span(str(p))
    assert r["duration"] == "20m 0s"
    assert r["start"].startswith("2024-12-31")
