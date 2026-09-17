# logspan

Answer "what time window does this log actually cover?" for one file or a whole
directory, fast.

For each file, `logspan` prints the size, line count, first timestamp, last
timestamp and the duration between them. It reads only the head and tail of
each file to find the timestamps, so multi-gigabyte logs finish in well under a
second (the line count is the only full pass, done with a buffered byte scan).

Written for Redpanda debug bundles, whose `logs/` directory mixes Seastar-style
broker logs with JSON sidecar logs, but it works on most logs.

## Install

```sh
uv tool install git+<repo-url>          # or: pipx install git+<repo-url>
# from a checkout:
uv tool install .
```

No dependencies beyond the Python 3.9+ standard library. The single file
`src/logspan/__init__.py` can also be copied anywhere and run directly.

## Usage

```
logspan [-j] FILE|DIR ...
  -j            JSON output (one object per file)
  -h, --help    show this help
  -V, --version show version
```

Directories are expanded to their immediate files (not recursive).

```
$ logspan redpanda-2-debug-bundle/logs
file                       size     lines  start                     end                       duration
redpanda-0-redpanda.txt   41.4M   136,512  2026-09-15 14:22:31.242   2026-09-15 14:25:12.255   2m 41s
redpanda-0-sidecar.txt    82.8K       792  2026-09-14 00:01:45.414Z  2026-09-15 14:22:45.987Z  1d 14h 21m 0s
redpanda-6-redpanda.txt   13.1M    54,175  2026-09-14 15:04:55.778   2026-09-15 14:24:58.920   23h 20m 3s
redpanda-0-init-tuning.txt    0B         0  (empty)
```

JSON output is one object per line, suitable for `jq`:

```
$ logspan -j redpanda-2-redpanda.txt
{"file": "redpanda-2-redpanda.txt", "size_bytes": 10333319, "size": "9.9M", "lines": 32491,
 "status": "ok", "start": "2026-09-15 14:24:30.060", "end": "2026-09-15 14:25:02.056",
 "duration": "31s", "duration_seconds": 31.996}
```

`status` is one of `ok`, `empty`, `no timestamp found`, `not found`.

## Recognised timestamp formats

| Style | Example |
|---|---|
| Redpanda / Seastar | `INFO  2026-09-15 14:22:31,242 [shard 0] ...` |
| ISO-8601 / RFC3339 (JSON `ts`, Go, Kubernetes) | `2026-09-14T00:01:45.414Z`, `2026-09-14 00:01:45.414+02:00` |
| syslog | `Sep 15 14:22:31` (year assumed to be the current year) |
| Apache / nginx access | `[15/Sep/2026:14:22:31 +0000]` |
| Epoch seconds or millis at line start | `1789000000.123`, `1789000000123` |

Timestamps with a zone are printed with `Z` or an offset; naive ones are
printed as-is. If the first and last timestamps disagree on having a zone,
the duration is computed on the naive wall-clock values.

## Caveats

* Only the first 256 KB and last 256 KB of each file are searched for a
  timestamp. Files with a very long untimestamped preamble or trailer report
  `no timestamp found`.
* The tail scan drops the first line of the tail chunk on the assumption it is
  partial. On files between 256 KB and ~512 KB with one enormous line this could
  skip a real line; in practice irrelevant.
* Duration is computed between the first and last *found* timestamp, so an
  out-of-order line at either end skews it.

## Development

```sh
uv sync
uv run pytest
uv run logspan tests/fixtures
```

## License

MIT
