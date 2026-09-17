---
name: using-logspan
description: Use when asked what time range, start/end time, or duration a log file or directory of logs covers, or before writing head/tail, awk, grep, or date pipelines to find the first and last timestamps in log files.
---

# Using logspan

`logspan` prints size, line count, first timestamp, last timestamp and
duration for each log file given. It reads only the head and tail of each
file, so it finishes in milliseconds regardless of file size. Run it instead
of writing a timestamp-extraction pipeline; the output is already the answer.

`logspan --help` lists all options and every timestamp format it recognises
(Seastar, ISO-8601/RFC3339, syslog, Apache, epoch).

## Calling it

| Task | Command |
|---|---|
| Files or a directory | `logspan FILE... ` or `logspan DIR` |
| Recurse into subdirectories | `logspan -r DIR` |
| Only matching file names | `logspan -r -g '*.log,*.txt' DIR` |
| Hide zero-byte files | `--skip-empty` |
| JSON, one object per line | `logspan -j ... \| jq 'select(.status=="ok")'` |
| Show full paths in the table | `--full-path` |

Quote `-g` patterns so the shell does not expand them. `-g` applies to files
found under directories; files named explicitly are always included. Zip
archives are not opened.

## Reading the output

- `status` is `ok`, `empty`, `no timestamp found`, or `not found`. Config,
  JSON dumps and binary files report `no timestamp found`; that is expected.
- A negative duration means the file is not chronological (for example a
  directory listing). Exclude it with `-g`.
- Timestamps print as written in the file. A trailing `Z` or offset means the
  source had a zone; otherwise it is whatever zone the writer used.
- Only the first and last timestamps are read. Gaps or ordering problems
  inside a file are not detected; check a specific minute with
  `grep -c 'YYYY-MM-DD HH:MM' FILE` if that matters.

## Example

"What time range do the logs in this debug bundle cover?"

```
logspan -r -g '*.txt,*.log' --skip-empty bundle/
```

Report the window per file and, for a set of files that should overlap, the
intersection (latest start to earliest end). Files with much shorter windows
than their peers were usually rotated or restarted recently.

If not installed: `uv tool install git+ssh://git@github.com/jbarnes7952/logspan`
