# tzdig

**[Open tzdig in your browser](https://darpan-97.github.io/tzdig/)** · [on a phone](https://darpan-97.github.io/tzdig/mobile.html) · [download for Windows](https://github.com/darpan-97/tzdig/releases/latest/download/tzdig.exe)

Convert timestamps between formats and time zones. Give it a value or a whole log, and get UTC and
the local time in any zone, with the daylight-saving rules for that date.

```
$ tzdig 1727104445123 --in "new york, sydney"
1727104445123   unix milliseconds
  UTC           2024-09-23 15:14:05.123
  US New York   2024-09-23 11:14:05.123 EDT (UTC-4)
  AU Sydney     2024-09-24 01:14:05.123 AEST (UTC+10)
```

It runs locally and never uses the network.

## Get it

- **Windows:** `tzdig.exe` from [Releases](https://github.com/darpan-97/tzdig/releases). One file,
  nothing to install. It is not code-signed, so Windows may warn the first time it runs.
- **Browser:** [darpan-97.github.io/tzdig](https://darpan-97.github.io/tzdig/), or
  [mobile.html](https://darpan-97.github.io/tzdig/mobile.html) on a phone. Each page is one file
  that runs in the browser; saved to disk (`web/`), it works offline.

## Use

```
tzdig 1727104445123                       a value, in UTC
tzdig 1727104445123 --in est,aest         and in other zones
tzdig 1727104445123 --in au               and in every zone of a country
tzdig "03/04/2024 10:00"                  a date that reads two ways shows both
tzdig "24 Sep 2026 1:23 pm" --from in     a time with no zone, read as India's time
tzdig --in est < app.log                  every timestamp in a file
Get-Content app.log | tzdig --in est      the same in PowerShell
tzdig --json 133712345678901234           JSON output
tzdig --all 45558                         every reading of a number, not only 1990-2040
tzdig --year 2023 < syslog.txt            the year of dates written without one
tzdig --zones                             every country code
tzdig --zones au                          one country's zones
```

## Formats

Numbers: Unix seconds, milliseconds, microseconds and nanoseconds, Windows FILETIME (decimal or
`0x` hex), Chrome/WebKit, Apple/Cocoa, Excel dates and .NET ticks.

Dates with a time of day:

| Layout | Example |
|---|---|
| ISO 8601 | `2024-09-23T20:44:05.123+05:30`, `2024-09-23 11:14:05 -0400`, `20240923T151405Z` |
| Email, HTTP | `Mon, 23 Sep 2024 11:14:05 -0400` |
| Web server log | `[23/Sep/2024:15:26:11 +0000]` |
| Syslog | `Sep 23 15:27:40` |
| Unix `date` | `Mon Sep 23 15:14:05 UTC 2024` |
| Month name | `Sep 23, 2024 3:14:05 PM`, `23-Sep-2024 15:14:05` |
| Numeric | `2024/09/23 15:25:03`, `9/23/2024 3:14:05 PM`, `23.09.2024 15:14:05` |
| LDAP, certificate | `20240923151405.0Z`, `240923151405Z` |

When a value can be read more than one way, every reading is shown:

- a bare number: each format that lands between 1990 and 2040 (`--all` for every one)
- `03/04/2024`: 4 March and 3 April, unless one of the numbers is over 12
- a zone abbreviation with several meanings: `IST` (Ireland, Israel, India), `CST` (US, Cuba,
  China), `CDT` (US, Cuba), `PST` (US, Philippines)

A time with no zone is read as UTC, unless `--from` names the zone it is in (on the web page, the
"Times with no zone are in" box; on the phone page, a switch for the phone's own zone). A time the
clocks show twice as they fall back gets both readings, and one they skip is said not to exist. A
date with no year is read as the latest year that is not in the future. The output says each time
which of these it assumed. Not read: a date without a time, a time without a date, relative times
("5 minutes ago") and month names in other languages.

## Zones

Every zone in the IANA time zone database (2026c), with its rules from 1970 to 2069. Name zones with
`--in`, comma-separated:

- a country code: `au`, `us`, `in` -- every zone of that country (`uk` is Britain)
- a country code and a city: `"au sydney"`, `us/new york`
- a city: `sydney`
- an IANA name: `Australia/Sydney`
- an abbreviation: `est`, `cst`, `mst`, `pst`, `gmt`, `bst`, `cet`, `ist`, `aest`, `aedt`, `awst`,
  `jst`, `sgt`, `gst`, `nzst`

Each zone is shown with the abbreviation in effect on that date: EST or EDT, AEST or AEDT.

## Build

tzdig is written in nitro, and building it needs the nitro toolchain (v1.170 or later, not public
yet). `bash build.sh` makes the native binary, the web pages and the C++, Rust, JavaScript,
WebAssembly and AOT builds, and checks each one against the known answers in `tests/vectors.tsv`.
Those are made by `tools/make_vectors.py` from Python's datetime and the IANA database, and checked
again with .NET by `tools/check_vectors.ps1`.

## License

MIT. The zone table is generated from the IANA time zone database, which is in the public domain.
