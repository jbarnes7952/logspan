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
