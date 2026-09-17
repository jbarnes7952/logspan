---
name: using-logspan
description: Use when asked what time window, date range, start/end time, or duration a log file or directory of logs covers, or when checking log coverage across brokers in a Redpanda debug bundle before deeper log analysis. Also use when tempted to hand-roll head/tail, awk, or date pipelines to find first and last timestamps in large logs.
---

# Using logspan

`logspan` prints size, line count, first timestamp, last timestamp and duration
for log files. It reads only the head and tail of each file, so a 45 MB broker
log takes milliseconds. **Never hand-roll awk/grep/date pipelines for "what
window does this log cover" — run `logspan` first.** macOS awk lacks `mktime`
and full scans of a bundle's logs take a minute; `logspan` does a bundle's
`logs/` directory in well under a second.

Run `logspan --help` for the full option list.

## Quick reference

| Task | Command |
|---|---|
| One bundle's `logs/` dir | `logspan --skip-empty BUNDLE/logs` |
| Whole bundle, text logs only | `logspan -r -g '*-redpanda.txt,*-sidecar.txt,*.log' --skip-empty BUNDLE` |
| Only broker logs | `logspan -g 'redpanda-*-redpanda.txt' BUNDLE/logs` |
| Several bundles under CWD | `logspan -r -g '*-redpanda.txt' --skip-empty .` |
| Machine-readable | `logspan -j ... \| jq 'select(.status=="ok")'` |
| Not installed? | `uv tool install git+ssh://git@github.com/jbarnes7952/logspan` |

Quote `-g` patterns. Files named explicitly bypass the `-g` filter.

## Reading the output

- **Always state the intersection window**: latest start to earliest end
  across the broker logs. That is the only range where cross-broker
  correlation is possible, and it is often seconds long.
- **Broker logs covering minutes while sidecars cover a day** is normal for
  Kubernetes bundles: the container runtime caps log size (~40 MB) and chatty
  brokers hit it in ~3 minutes. Name the brokers with the least coverage.
- **A broker with a tiny window well under the size cap** was either rotated
  or restarted. Check the first line: a startup banner (`grep -c 'Welcome to
  the Redpanda community' FILE`) means restart; no banner means the container
  log rotated just before collection.
- **One broker with far longer coverage** is the quiet one; it is the only
  place events from earlier will appear.
- **Negative duration** means the file is not a chronological log (for
  example a directory listing with mtimes). Ignore it or exclude with `-g`.
- **`no timestamp found`** on `.yaml`/`.json` dumps is expected, not an error.
- **`empty`** files are init-container logs; hide with `--skip-empty`.
- Timestamps are printed as written in the log. Redpanda broker logs are
  UTC without a zone marker; sidecar JSON logs carry `Z`.

## Outside `logs/`

Other bundle directories rarely hold text logs. `controller-logs/` are binary
Raft segments (always `no timestamp found`). `crash_reports/` file names are
epoch milliseconds; decode with `date -u -r $((ms/1000))`. `k8s/*.json` dates
are object creation times, not a log window. `data-dir.txt` is a directory
listing with mtimes and gives a meaningless or negative duration. Use the
`-g` pattern above rather than a bare `-r` over the bundle root.

## Limits

`logspan` uses only the first and last parseable timestamp. It does not detect
gaps, out-of-order lines, or rate changes inside the file. When those matter,
use `logspan` for the window first, then target a full scan at the specific
file and range it identified.

## Example

Partner: "What time range do the logs in this bundle cover?"

```
logspan -r -g '*-redpanda.txt,*-sidecar.txt' --skip-empty redpanda-2-debug-bundle
```

Then summarise: intersection window across brokers, outliers with why
(rotated vs restarted vs quiet), and whether the incident time the customer
reported falls inside it. If it does not, say so
and ask for a bundle collected during the event.
