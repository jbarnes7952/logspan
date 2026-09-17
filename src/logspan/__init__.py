"""logspan - print start time, end time and duration of one or more log files.

Usage: logspan [-j] [-r] [-g PATTERN]... [--skip-empty] [--full-path] FILE|DIR ...
  -j, --json        JSON output (one object per file)
  -r, --recursive   descend into subdirectories
  -g, --glob PAT    only consider files whose name matches PAT (fnmatch style,
                    e.g. '*.log'); repeatable, or comma-separated. Applies to
                    files found under directory arguments, not to files named
                    explicitly. Quote the pattern so the shell does not expand it.
  --skip-empty      omit zero-byte files from the output
  --full-path       show the full path in the table instead of the path
                    relative to the directory argument
  --completion zsh  print a zsh completion script (see README)
  -h, --help    show this help
  -V, --version show version

Columns: size, line count, first timestamp, last timestamp, duration.

Finds the first and last parseable timestamp in each file. Reads forward from
the head and backward from the tail so large files are cheap. Handles:
  * Redpanda/Seastar:  INFO  2026-09-15 14:22:31,242 [shard 0] ...
  * ISO-8601 / RFC3339 (JSON "ts", Go, k8s):  2026-09-14T00:01:45.414Z
  * ISO with space separator and dot/comma millis, optional tz offset
  * syslog:  Sep 15 14:22:31  (no year: the file's mtime year is assumed for
    the last entry, a Dec->Jan wrap moves the first entry back a year; such
    rows are marked "year assumed")
  * Apache/nginx:  [15/Sep/2026:14:22:31 +0000]
  * Epoch seconds/millis at line start
"""
import argparse, fnmatch, json, os, re, sys

__version__ = "0.1.0"
from datetime import datetime, timezone, timedelta

CHUNK = 256 * 1024          # bytes to scan at each end before giving up
MAX_LINES = 5000            # lines to try at each end

MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

ISO = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:[.,](\d{1,9}))?\s*(Z|[+-]\d{2}:?\d{2}|UTC|GMT)?")
SYSLOG = re.compile(
    r"(?<![A-Za-z])(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})"
    r"\s+(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,9}))?")
APACHE = re.compile(
    r"\[(\d{2})/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/(\d{4}):"
    r"(\d{2}):(\d{2}):(\d{2})\s*([+-]\d{4})?\]")
EPOCH = re.compile(r"^\s*\[?(\d{10})(?:[.,](\d{3,9})|(\d{3}))?\]?\b")


def _frac_to_us(frac):
    if not frac:
        return 0
    return int((frac + "000000")[:6])


def _tz(s):
    if not s or s in ("Z", "UTC", "GMT"):
        return timezone.utc
    s = s.replace(":", "")
    sign = 1 if s[0] == "+" else -1
    return timezone(sign * timedelta(hours=int(s[1:3]), minutes=int(s[3:5])))


def parse_ts(line, default_year=None):
    """Return (datetime, has_tz, year_assumed) for the first timestamp on the
    line, or None. year_assumed is True for formats that carry no year; those
    get `default_year` (the current year if not given)."""
    m = ISO.search(line)
    if m:
        y, mo, d, h, mi, s, frac, tz = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s),
                          _frac_to_us(frac), tzinfo=_tz(tz) if tz else None)
            return dt, bool(tz), False
        except ValueError:
            pass
    m = APACHE.search(line)
    if m:
        d, mon, y, h, mi, s, tz = m.groups()
        try:
            return datetime(int(y), MONTHS[mon], int(d), int(h), int(mi), int(s),
                            tzinfo=_tz(tz) if tz else None), bool(tz), False
        except ValueError:
            pass
    m = SYSLOG.search(line)
    if m:
        mon, d, h, mi, s, frac = m.groups()
        try:
            year = default_year or datetime.now().year
            return datetime(year, MONTHS[mon], int(d), int(h),
                            int(mi), int(s), _frac_to_us(frac)), False, True
        except ValueError:
            pass
    m = EPOCH.search(line)
    if m:
        secs, frac, ms = m.groups()
        us = _frac_to_us(frac) if frac else (int(ms) * 1000 if ms else 0)
        return datetime.fromtimestamp(int(secs), tz=timezone.utc).replace(
            microsecond=us), True, False
    return None


def head_lines(path):
    with open(path, "rb") as f:
        data = f.read(CHUNK)
    for i, ln in enumerate(data.splitlines()):
        if i >= MAX_LINES:
            break
        yield ln.decode("utf-8", "replace")


def tail_lines(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - CHUNK))
        data = f.read()
    lines = data.splitlines()
    if size > CHUNK and lines:
        lines = lines[1:]           # first line is probably partial
    for i, ln in enumerate(reversed(lines)):
        if i >= MAX_LINES:
            break
        yield ln.decode("utf-8", "replace")


def first_ts(lines, default_year=None):
    for ln in lines:
        r = parse_ts(ln, default_year)
        if r:
            return r
    return None


def fmt_dt(dt):
    s = dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    if dt.tzinfo:
        off = dt.strftime("%z")
        s += "Z" if off in ("+0000", "") else f"{off[:3]}:{off[3:]}"
    return s


def fmt_dur(td):
    total = int(td.total_seconds())
    neg = total < 0
    total = abs(total)
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if d or h:
        parts.append(f"{h}h")
    if d or h or m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return ("-" if neg else "") + " ".join(parts)


def fmt_size(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def count_lines(path):
    n = 0
    last = b""
    with open(path, "rb") as f:
        for buf in iter(lambda: f.read(1 << 20), b""):
            n += buf.count(b"\n")
            last = buf[-1:]
    if last and last != b"\n":
        n += 1                      # unterminated final line
    return n


def span(path, name=None):
    name = name or os.path.basename(path)
    if not os.path.isfile(path):
        return {"file": path, "name": name, "size_bytes": 0, "size": "-",
                "lines": 0, "status": "not found"}
    size = os.path.getsize(path)
    base = {"file": path, "name": name, "size_bytes": size,
            "size": fmt_size(size), "lines": count_lines(path) if size else 0}
    if size == 0:
        return {**base, "status": "empty"}
    # Year-less formats get the year the file was last written, which is the
    # year of its final entry.
    mtime_year = datetime.fromtimestamp(os.path.getmtime(path)).year
    a = first_ts(head_lines(path), mtime_year)
    b = first_ts(tail_lines(path), mtime_year)
    if not a or not b:
        return {**base, "status": "no timestamp found"}
    (start, tz_a, ya), (end, tz_b, yb) = a, b
    if tz_a != tz_b:                       # mixed aware/naive; compare naively
        start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
    year_assumed = ya or yb
    if ya and yb and end < start:
        # Year-less format (syslog) wrapping a year boundary: the file is in
        # order, the assumed year is what is wrong. The end matches the
        # file's mtime year, so the start belongs to the year before.
        start = start.replace(year=start.year - 1)
    dur = end - start
    return {**base, "status": "ok",
            "start": fmt_dt(start), "end": fmt_dt(end),
            "duration": fmt_dur(dur), "duration_seconds": dur.total_seconds(),
            "year_assumed": year_assumed}


def matches(name, patterns):
    return not patterns or any(fnmatch.fnmatch(name, g) for g in patterns)


def expand(args, recursive=False, patterns=()):
    """Yield (path, display_name). Files under a directory argument are
    displayed relative to that directory and filtered by `patterns`
    (matched against the basename); bare file arguments are always included."""
    for a in args:
        if os.path.isdir(a):
            if recursive:
                for root, dirs, files in os.walk(a):
                    dirs.sort()
                    for n in sorted(files):
                        if matches(n, patterns):
                            p = os.path.join(root, n)
                            yield p, os.path.relpath(p, a)
            else:
                for n in sorted(os.listdir(a)):
                    p = os.path.join(a, n)
                    if os.path.isfile(p) and matches(n, patterns):
                        yield p, n
        else:
            yield a, a


def completion_script(shell):
    """Return the completion script bundled at src/logspan/completions/."""
    here = os.path.join(os.path.dirname(__file__), "completions")
    with open(os.path.join(here, f"_logspan.{shell}")) as f:
        return f.read()


def build_parser():
    ap = argparse.ArgumentParser(
        prog="logspan", add_help=False,
        description="Print size, line count, first/last timestamp and duration of log files.")
    ap.add_argument("paths", nargs="*", metavar="FILE|DIR")
    ap.add_argument("-j", "--json", action="store_true", dest="as_json")
    ap.add_argument("-r", "--recursive", action="store_true")
    ap.add_argument("-g", "--glob", action="append", default=[], metavar="PAT")
    ap.add_argument("--skip-empty", action="store_true")
    ap.add_argument("--full-path", action="store_true")
    ap.add_argument("--completion", choices=["zsh"], metavar="SHELL")
    ap.add_argument("-h", "--help", action="store_true")
    ap.add_argument("-V", "--version", action="store_true")
    return ap


def main(argv):
    ap = build_parser()
    try:
        ns = ap.parse_args(argv)
    except SystemExit:
        return 2
    if ns.version:
        print(f"logspan {__version__}")
        return 0
    if ns.completion:
        print(completion_script(ns.completion), end="")
        return 0
    if ns.help or not ns.paths:
        print(__doc__.strip(), file=sys.stdout if ns.help else sys.stderr)
        return 0 if ns.help else 2
    patterns = [g for chunk in ns.glob for g in chunk.split(",") if g]
    as_json, skip_empty, recursive, full_path = (
        ns.as_json, ns.skip_empty, ns.recursive, ns.full_path)
    paths = ns.paths
    rows = [span(p, p if full_path else n)
            for p, n in expand(paths, recursive, patterns)]
    if skip_empty:
        rows = [r for r in rows if r["status"] != "empty"]
    if not rows:
        return 0
    if as_json:
        for r in rows:
            print(json.dumps(r))
        return 0
    w = max(len(r["name"]) for r in rows)
    print(f"{'file':<{w}}  {'size':>7} {'lines':>9}  {'start':<25} {'end':<25} duration")
    for r in rows:
        name = r["name"]
        pre = f"{name:<{w}}  {r['size']:>7} {r['lines']:>9,}  "
        if r["status"] != "ok":
            print(pre + f"({r['status']})")
        else:
            note = "  (year assumed)" if r.get("year_assumed") else ""
            print(pre + f"{r['start']:<25} {r['end']:<25} {r['duration']}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


def cli():
    """Console-script entry point."""
    sys.exit(main(sys.argv[1:]))
