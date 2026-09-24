#!/usr/bin/env python3
"""make_vectors.py -- the known answers `tzdig` is tested against.

They come from Python's own datetime and the IANA time zone database (zoneinfo). tools/check_vectors.ps1
checks the same file with .NET, a second implementation written by other people: a value both agree on
is trusted, a value they disagree on is a finding to look at, not a test to weaken.

Run on Linux or WSL, where zoneinfo reads the system's IANA database:
    python3 tools/make_vectors.py > tests/vectors.tsv

Seven kinds of row, tab-separated:
    now      <utc>                            "now" for the rows after it: which year a date written
                                              without one (syslog's Sep 23 15:27:40) is in
    from     <zone as typed>   <IANA zone>    --from for the rows after it: the zone of times written
                                              without one ("utc" to stop)
    format   <input>   <reading>   <utc> ...   the input read that way; a zone abbreviation that means
                                              several offsets gives one utc per offset, west to east
    bare     <input>   <every reading, as reading=utc, space-separated, in tzdig's order>
    zone     <utc>     <IANA zone>   <local time>   <offset>   <abbreviation>
    pick     <one name, as typed after --in>   <the IANA zones it chooses, space-separated, in order>
    find     <a line of text>   <the timestamps tzdig finds in it, " | " between them>

A date written as text is read here by strptime, with a format written out for that one row, or by
email.utils -- never by anything that guesses. The find rows are the one thing written by hand: which
parts of a log line are timestamps is tzdig's own rule, and they pin it.
"""
import datetime as dt
import email.utils
import sys
import zoneinfo

UTC = dt.timezone.utc
EPOCH = dt.datetime(1970, 1, 1, tzinfo=UTC)
FROM_1601 = 11644473600          # seconds from 1601-01-01 to 1970-01-01 (FILETIME, WebKit)
FROM_2001 = 978307200            # seconds from 1970-01-01 to 2001-01-01 (Apple/Cocoa)
FROM_0001 = 62135596800          # seconds from 0001-01-01 to 1970-01-01 (.NET ticks)
EXCEL_EPOCH = dt.datetime(1899, 12, 30, tzinfo=UTC)
WINDOW = (dt.datetime(1990, 1, 1, tzinfo=UTC), dt.datetime(2041, 1, 1, tzinfo=UTC))


def iso(seconds, frac=""):
    """seconds since 1970 (an integer) and the fraction digits the input carried -> ISO 8601 UTC"""
    t = EPOCH + dt.timedelta(seconds=seconds)          # (strftime's %Y does not pad years before 1000)
    return "%04d-%s" % (t.year, t.strftime("%m-%dT%H:%M:%S")) + ("." + frac if frac else "") + "Z"


def split(n, per_second, digits):
    return iso(n // per_second, "%0*d" % (digits, n % per_second))


# every numeric reading, in the order `tzdig` lists them
FORMAT = [
    ("unix-s",   lambda n: iso(n)),
    ("unix-ms",  lambda n: split(n, 10**3, 3)),
    ("unix-us",  lambda n: split(n, 10**6, 6)),
    ("unix-ns",  lambda n: split(n, 10**9, 9)),
    ("filetime", lambda n: iso(n // 10**7 - FROM_1601, "%07d" % (n % 10**7))),
    ("webkit",   lambda n: iso(n // 10**6 - FROM_1601, "%06d" % (n % 10**6))),
    ("cocoa",    lambda n: iso(n + FROM_2001)),
    ("excel",    lambda n: (EXCEL_EPOCH + dt.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")),
    ("dotnet",   lambda n: iso(n // 10**7 - FROM_0001, "%07d" % (n % 10**7))),
]
READ = dict(FORMAT)


def in_window(utc):
    t = dt.datetime.strptime(utc[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return WINDOW[0] <= t < WINDOW[1]


# ── dates written as text ───────────────────────────────────────────────────────────────────────────

def cut(text, frac):
    """text without its fraction of a second (".123" or ",123"): %f reads no more than 6 digits"""
    if not frac:
        return text
    i = max(text.rfind("." + frac), text.rfind("," + frac))
    assert i >= 0, text
    return text[:i] + text[i + 1 + len(frac):]


def strp(text, fmt, frac="", east=0):
    """text read by strptime(fmt) -> ISO 8601 UTC with the input's fraction digits. frac: those digits,
    cut out first; east: the offset in minutes when fmt has no %z (0 when the text gives no zone: UTC)"""
    t = dt.datetime.strptime(cut(text, frac), fmt)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone(dt.timedelta(minutes=east)))
    return iso(int((t - EPOCH).total_seconds()), frac)


def guess_year(now, text, fmt):
    """the year tzdig gives a date written without one: the latest in which it is at most two days
    after now (a December line read in January is last year's)"""
    t0 = dt.datetime.strptime("2000 " + text, "%Y " + fmt)       # 2000: a leap year, so 29 Feb reads
    y = now.year
    while True:
        try:
            t = t0.replace(year=y, tzinfo=UTC)
        except ValueError:                                         # 29 Feb in a year without one
            y -= 1
            continue
        if (t - now).total_seconds() <= 2 * 86400:
            return y
        y -= 1


# Zone names the IANA database now writes as numbers but Java's Date.toString() still prints (checked
# with Java 8: TimeZone.getDisplayName(false, SHORT, Locale.US)) and people still write, in minutes east.
# The one table here that is not derived: tzdig carries the same one (legacy_abbr), so these rows test
# its arithmetic, not its facts.
LEGACY = {"SGT": 480, "GST": 240, "AST": 180, "ICT": 420, "PHT": 480, "MYT": 480, "BDT": 360, "NPT": 345,
          "IRST": 210, "IRDT": 270, "AFT": 270, "TRT": 180, "UZT": 300, "AZT": 240, "MMT": 390, "FJT": 720,
          "BRT": -180, "BRST": -120, "ART": -180, "CLT": -240, "CLST": -180, "COT": -300, "PET": -300,
          "VET": -240}

_YEAR_USES = {}


def year_uses(year):
    """{abbreviation: {offsets in minutes}} that some IANA zone uses during year, sampled daily at noon UTC"""
    if year not in _YEAR_USES:
        found = {}
        names = [n for n in sorted(zoneinfo.available_timezones())
                 if not n.startswith(("posix/", "right/")) and n not in ("Factory", "localtime")]
        for name in names:
            z = zoneinfo.ZoneInfo(name)
            t = dt.datetime(year, 1, 1, 12, tzinfo=UTC)
            while t.year == year:
                l = t.astimezone(z)
                a = l.tzname()
                if a and a[0].isalpha():
                    found.setdefault(a, set()).add(int(l.utcoffset().total_seconds()) // 60)
                t += dt.timedelta(days=1)
        _YEAR_USES[year] = found
    return _YEAR_USES[year]


def meanings(abbr, year):
    """every offset the IANA database gives abbr in some zone from the start of the year before to the end
    of the year after -- so PST in July still has Los Angeles's -8 -- and its meaning in LEGACY; west to east"""
    found = set()
    for y in (year - 1, year, year + 1):
        found |= year_uses(y).get(abbr, set())
    if abbr in LEGACY:
        found.add(LEGACY[abbr])
    return sorted(found)


# (input, reading, strptime format for the input with its fraction cut out, the fraction's digits,
#  minutes east when the format has no %z)
TEXT = [
    # ISO 8601, and what logs write close to it
    ("2024-09-23 11:14:05 -0400", "iso8601", "%Y-%m-%d %H:%M:%S %z", "", 0),          # git, Rails, ls
    ("2024-09-23 11:14:05 +05:30", "iso8601", "%Y-%m-%d %H:%M:%S %z", "", 0),
    ("2024-09-23 11:14:05.123456789 -0400", "iso8601", "%Y-%m-%d %H:%M:%S %z", "123456789", 0),  # stat
    ("2024-09-23T15:14:05.123456789Z", "iso8601", "%Y-%m-%dT%H:%M:%S%z", "123456789", 0),  # Docker
    ("2024-09-23 15:14:05,123", "iso8601", "%Y-%m-%d %H:%M:%S", "123", 0),             # Python, log4j
    ("2024-09-23 15:14:05.123456789 +0000 UTC", "iso8601", "%Y-%m-%d %H:%M:%S %z UTC", "123456789", 0),  # Go
    ("2024-09-23T20:44:05.123+05:30[Asia/Kolkata]", "iso8601", "%Y-%m-%dT%H:%M:%S%z[Asia/Kolkata]", "123", 0),  # Java
    ("2024-09-23 15:14:05.123+00", "iso8601", "%Y-%m-%d %H:%M:%S+00", "123", 0),        # PostgreSQL
    ("2024-09-23 15:14:05 UTC", "iso8601", "%Y-%m-%d %H:%M:%S UTC", "", 0),
    ("2024-09-23 15:14:05Z", "iso8601", "%Y-%m-%d %H:%M:%S%z", "", 0),                  # .NET's "u"
    ("2024-09-23T15:14", "iso8601", "%Y-%m-%dT%H:%M", "", 0),
    ("2024-W39-1T15:14:05Z", "iso8601", "%G-W%V-%uT%H:%M:%S%z", "", 0),                # week date
    ("2024-267T15:14:05Z", "iso8601", "%Y-%jT%H:%M:%S%z", "", 0),                      # ordinal date
    ("20240923T151405Z", "iso8601", "%Y%m%dT%H%M%S%z", "", 0),                         # basic (iCalendar)
    ("20240923T204405+0530", "iso8601", "%Y%m%dT%H%M%S%z", "", 0),
    ("2024-09-23_15-14-05", "iso8601", "%Y-%m-%d_%H-%M-%S", "", 0),                    # file names
    # the compact forms
    ("20240923151405.0Z", "ldap", "%Y%m%d%H%M%S%z", "0", 0),                           # AD whenCreated
    ("20240923204405+0530", "ldap", "%Y%m%d%H%M%S%z", "", 0),
    ("20240923151405", "compact", "%Y%m%d%H%M%S", "", 0),
    ("20240923_151405", "compact", "%Y%m%d_%H%M%S", "", 0),                            # Android photos
    # year first, not ISO
    ("2024/09/23 15:25:03", "ymd", "%Y/%m/%d %H:%M:%S", "", 0),                        # Palo Alto, nginx, Go
    ("2024/9/3 15:25:03.1234567", "ymd", "%Y/%m/%d %H:%M:%S", "1234567", 0),           # Windows Update
    ("2024.09.23 15:14:05", "ymd", "%Y.%m.%d %H:%M:%S", "", 0),
    # month first, as the US writes it (a day over 12, so there is no other reading)
    ("9/23/2024 3:14:05 PM", "mdy", "%m/%d/%Y %I:%M:%S %p", "", 0),                    # Windows, Excel
    ("09/23/24 3:14:05.123 PM", "mdy", "%m/%d/%y %I:%M:%S %p", "123", 0),              # Splunk
    ("9/23/2024, 3:18:02.447 PM", "mdy", "%m/%d/%Y, %I:%M:%S %p", "447", 0),           # Sentinel
    ("09/23/24,15:14:05", "mdy", "%m/%d/%y,%H:%M:%S", "", 0),                          # Windows DHCP
    ("12/31/2024 11:59 PM", "mdy", "%m/%d/%Y %I:%M %p", "", 0),
    ("1/1/2024 12:00:00 AM", "mdy", "%m/%d/%Y %I:%M:%S %p", "", 0),                    # the same either way
    # day first
    ("23/09/2024 15:14:05", "dmy", "%d/%m/%Y %H:%M:%S", "", 0),                        # UK, India, AU
    ("23.09.2024 15:14:05", "dmy", "%d.%m.%Y %H:%M:%S", "", 0),                        # Germany, SAP
    ("01.02.2024 15:14:05", "dmy", "%d.%m.%Y %H:%M:%S", "", 0),                        # dots: day first only
    ("23-09-2024 15:14", "dmy", "%d-%m-%Y %H:%M", "", 0),
    ("23/09/2024  03:14 PM", "dmy", "%d/%m/%Y %I:%M %p", "", 0),                       # Windows dir
    # a month's name
    ("23/Sep/2024:15:26:11 +0000", "clf", "%d/%b/%Y:%H:%M:%S %z", "", 0),             # Apache, nginx, S3
    ("23/Sep/2024:08:26:11 -0700", "clf", "%d/%b/%Y:%H:%M:%S %z", "", 0),
    ("Mon, 23 Sep 2024 11:14:05 -0400 (EDT)", "rfc2822", "%a, %d %b %Y %H:%M:%S %z (EDT)", "", 0),
    ("23 Sep 2024 15:14:05 GMT", "rfc2822", "%d %b %Y %H:%M:%S GMT", "", 0),           # HTTP
    ("23 Sep 2024 15:14:05,123", "month-name", "%d %b %Y %H:%M:%S", "123", 0),         # log4j, Redis
    ("Sep 23, 2024 3:14:05 PM", "month-name", "%b %d, %Y %I:%M:%S %p", "", 0),         # java.util.logging
    ("September 23, 2024 at 3:14:05 PM", "month-name", "%B %d, %Y at %I:%M:%S %p", "", 0),  # macOS
    ("Sep 23, 2024 @ 15:14:05.123", "month-name", "%b %d, %Y @ %H:%M:%S", "123", 0),   # Kibana
    ("Sep. 23, 2024 15:14:05", "month-name", "%b. %d, %Y %H:%M:%S", "", 0),            # CrowdStrike
    ("23-Sep-2024 15:14:05.123", "month-name", "%d-%b-%Y %H:%M:%S", "123", 0),         # Tomcat, BIND
    ("23-SEP-24 03.14.05.123000 PM", "month-name", "%d-%b-%y %I.%M.%S %p", "123000", 0),  # Oracle
    ("Monday, September 23, 2024 3:14:05 PM", "month-name", "%A, %B %d, %Y %I:%M:%S %p", "", 0),  # PowerShell
    ("Monday, 23 September 2024 3:14:05 PM", "month-name", "%A, %d %B %Y %I:%M:%S %p", "", 0),
    ("Sep 23 2024 15:27:40", "month-name", "%b %d %Y %H:%M:%S", "", 0),                # Cisco ASA
    ("23Sep2024 15:14:05", "month-name", "%d%b%Y %H:%M:%S", "", 0),                    # Check Point
    ("Sep 23 2024  3:14PM", "month-name", "%b %d %Y %I:%M%p", "", 0),                  # SQL Server
    ("2024-Sep-23 15:14:05", "month-name", "%Y-%b-%d %H:%M:%S", "", 0),
    ("Mon Sep 23 2024 11:14:05 GMT-0400 (Eastern Daylight Time)", "month-name",
     "%a %b %d %Y %H:%M:%S GMT%z (Eastern Daylight Time)", "", 0),                      # JavaScript
    # the year after the time
    ("Mon Sep 23 15:14:05 2024", "ctime", "%a %b %d %H:%M:%S %Y", "", 0),              # asctime, HTTP
    ("Mon Sep 23 15:14:05 UTC 2024", "ctime", "%a %b %d %H:%M:%S UTC %Y", "", 0),      # date, Java
    ("Sep 23 15:14:05 2024 GMT", "ctime", "%b %d %H:%M:%S %Y GMT", "", 0),             # openssl
    ("Mon Sep 23 11:14:05 2024 -0400", "ctime", "%a %b %d %H:%M:%S %Y %z", "", 0),     # git
    ("Mon Sep 23 15:14:05.123456 2024", "ctime", "%a %b %d %H:%M:%S %Y", "123456", 0),  # Apache's error log
]

# (now, [(input, reading, strptime format without a year, fraction digits)]): dates written without a year
YEARLESS = [
    ("2024-10-01T00:00:00Z", [
        ("Sep 23 15:27:40", "syslog", "%b %d %H:%M:%S", ""),
        ("Sep  3 15:27:40", "syslog", "%b %d %H:%M:%S", ""),
        ("Oct  3 00:00:00", "syslog", "%b %d %H:%M:%S", ""),              # two days ahead: this year
        ("Oct  3 00:00:01", "syslog", "%b %d %H:%M:%S", ""),              # a second more: last year
        ("Sep 23 15:14:05.123", "syslog", "%b %d %H:%M:%S", "123"),       # Cisco IOS
        ("I0923 15:14:05.123456", "klog", "I%m%d %H:%M:%S", "123456"),    # Kubernetes
        ("09-23 15:14:05.123", "logcat", "%m-%d %H:%M:%S", "123"),        # Android
    ]),
    ("2025-01-02T00:00:00Z", [
        ("Dec 31 23:59:59", "syslog", "%b %d %H:%M:%S", ""),
        ("Jan  3 12:00:00", "syslog", "%b %d %H:%M:%S", ""),
    ]),
    ("2025-06-01T00:00:00Z", [
        ("Feb 29 12:00:00", "syslog", "%b %d %H:%M:%S", ""),              # 2025 has none: 2024's
    ]),
]

# (input, reading, strptime format with the abbreviation as plain text, the abbreviation): read once
# for each offset the abbreviation has around then
ABBR = [
    ("Mon Sep 23 11:14:05 EDT 2024", "ctime", "%a %b %d %H:%M:%S EDT %Y", "EDT"),
    ("Mon, 23 Sep 2024 11:14:05 EDT", "rfc2822", "%a, %d %b %Y %H:%M:%S EDT", "EDT"),
    ("Mon Sep 23 20:44:05 IST 2024", "ctime", "%a %b %d %H:%M:%S IST %Y", "IST"),       # Ireland, Israel, India
    ("Sep 23 15:14:05 CST 2024", "ctime", "%b %d %H:%M:%S CST %Y", "CST"),             # US, Cuba, China
    ("Mon Sep 23 07:14:05 PST 2024", "ctime", "%a %b %d %H:%M:%S PST %Y", "PST"),       # US, Philippines
    ("Mon Sep 23 18:14:05 AST 2024", "ctime", "%a %b %d %H:%M:%S AST %Y", "AST"),       # Atlantic, Arabia
    ("Mon Sep 23 23:14:05 SGT 2024", "ctime", "%a %b %d %H:%M:%S SGT %Y", "SGT"),       # Java's Singapore
    ("2024-09-23 15:14:05 AEST", "iso8601", "%Y-%m-%d %H:%M:%S AEST", "AEST"),
    ("2024-01-15 12:00:00 BST", "iso8601", "%Y-%m-%d %H:%M:%S BST", "BST"),             # out of season
    ("1985-07-01 12:00:00 MSD", "iso8601", "%Y-%m-%d %H:%M:%S MSD", "MSD"),             # Moscow's old summer
    ("2012-07-01 12:00:00 MSK", "iso8601", "%Y-%m-%d %H:%M:%S MSK", "MSK"),             # +3, and +4 in 2011-14
]

# (input, [(reading, strptime format)]): a date that reads more than one way
BARE_TEXT = [
    ("03/04/2024 10:00", [("mdy", "%m/%d/%Y %H:%M"), ("dmy", "%d/%m/%Y %H:%M")]),
    ("04-03-2024 10:00:00", [("mdy", "%m-%d-%Y %H:%M:%S"), ("dmy", "%d-%m-%Y %H:%M:%S")]),
    ("13/04/2024 10:00", [("dmy", "%d/%m/%Y %H:%M")]),
]

def local_in(text, fmt, frac, zone):
    """every UTC instant at which the zone's clocks show text, earliest first: two where they fall back
    over it, none where they spring forward past it (both folds tried, each kept only if it comes back)"""
    t = dt.datetime.strptime(cut(text, frac), fmt)
    if t.tzinfo is not None:                                  # a zone written in the text wins
        return [iso(int((t - EPOCH).total_seconds()), frac)]
    z = zoneinfo.ZoneInfo(zone)
    found = []
    for fold in (0, 1):
        u = t.replace(tzinfo=z, fold=fold).astimezone(UTC)
        if u.astimezone(z).replace(tzinfo=None) == t and u not in found:
            found.append(u)
    return [iso(int((u - EPOCH).total_seconds()), frac) for u in sorted(found)]


# --from: (the zone as typed, its IANA name, [(input, reading, strptime format, fraction digits)]),
# after a "now" of 2024-10-01. Times written with no zone are that zone's local time; a zone written
# in the text, and a number, are not affected.
FROM = [
    ("in", "Asia/Kolkata", [
        ("24 September 2026 1:23 pm", "month-name", "%d %B %Y %I:%M %p", ""),
        ("2024-09-23 20:44:05", "iso8601", "%Y-%m-%d %H:%M:%S", ""),
        ("2024-09-23T11:14:05-04:00", "iso8601", "%Y-%m-%dT%H:%M:%S%z", ""),
    ]),
    ("us new york", "America/New_York", [
        ("2024-07-04 12:00:00", "iso8601", "%Y-%m-%d %H:%M:%S", ""),
        ("2024-11-03 01:30:00", "iso8601", "%Y-%m-%d %H:%M:%S", ""),          # shown twice: EDT, then EST
        ("11/03/2024 01:30:00.250", "mdy", "%m/%d/%Y %H:%M:%S", "250"),
        ("2024-03-10 02:30:00", "iso8601", "%Y-%m-%d %H:%M:%S", ""),          # skipped: no reading
        ("Mon Sep 23 11:14:05 2024", "ctime", "%a %b %d %H:%M:%S %Y", ""),
    ]),
    ("au sydney", "Australia/Sydney", [
        ("2024-04-07 02:30:00", "iso8601", "%Y-%m-%d %H:%M:%S", ""),          # shown twice: AEDT, then AEST
        ("2024-10-06 02:30:00", "iso8601", "%Y-%m-%d %H:%M:%S", ""),          # skipped
    ]),
]
# and a date with no year: its year first, as guess_year does, then the zone's local time
FROM_YEARLESS = ("us new york", "America/New_York", "Sep 23 15:27:40", "syslog", "%b %d %H:%M:%S")

# (a line of text, [the timestamps in it]), after a "now" of 2024-10-01: common log lines, and lines
# that must give nothing.
FIND = [
    ("Received: from mail.example.net (198.51.100.4) by mx.example.com; Mon, 23 Sep 2024 11:08:15 -0400",
     ["Mon, 23 Sep 2024 11:08:15 -0400"]),
    ('{"CreationTime":"2024-09-23T15:16:30","Operation":"FileAccessed","UserId":"user@example.com"}',
     ["2024-09-23T15:16:30"]),
    ('{"timestamp":1727104745123,"start":1727104744.281,"host":"ws-042"}',
     ["1727104745123", "1727104744.281"]),
    ("UtcTime: 2024-09-23 15:19:11.532 Image: C:/Windows/System32/notepad.exe",
     ["2024-09-23 15:19:11.532"]),
    ("pwdLastSet: 133716612000000000   lastLogonTimestamp: 133717005000000000   accountExpires: 9223372036854775807",
     ["133716612000000000", "133717005000000000", "9223372036854775807"]),
    ("1727105100.123456 CxyZ12 10.0.0.15 49812 198.51.100.4 443 tcp", ["1727105100.123456"]),
    ("1,2024/09/23 15:25:03,007951000012345,TRAFFIC,end,10.0.0.15,198.51.100.4,allow", ["2024/09/23 15:25:03"]),
    ('198.51.100.4 - - [23/Sep/2024:15:26:11 +0000] "GET /index.html HTTP/1.1" 200 512',
     ["23/Sep/2024:15:26:11 +0000"]),
    ("Sep 23 15:27:40 web01 sshd[2211]: Accepted publickey for deploy from 198.51.100.4 port 51022",
     ["Sep 23 15:27:40"]),
    ("type=EXECVE msg=audit(1727105460.512:8812): argc=2 a0=\"ls\"", ["1727105460.512"]),
    ("CEF:0|Vendor|Product|1.0|100|Name|3|rt=1727105580000 src=10.0.0.15 dst=198.51.100.4", ["1727105580000"]),
    ("rt=Sep 23 2024 15:14:05 UTC dst=10.0.0.1", ["Sep 23 2024 15:14:05 UTC"]),
    ("*Sep 23 15:14:05.123: %SYS-5-CONFIG_I: Configured from console", ["Sep 23 15:14:05.123"]),
    ('date=2024-09-23 time=15:14:05 devname="fw01" eventtime=1727104445123456789 tz="+1000"',
     ["2024-09-23 time=15:14:05", "1727104445123456789"]),
    ("I0923 15:14:05.123456    2024 server.go:42] started", ["I0923 15:14:05.123456"]),
    ("09-23 15:14:05.123  1234  5678 I ActivityManager: Start proc", ["09-23 15:14:05.123"]),
    ("IMG_20240923_151405.jpg and backup-20240923-151405.tar", ["20240923_151405", "20240923-151405"]),
    ('Started GET "/" for 127.0.0.1 at 2024-09-23 11:14:05 -0400', ["2024-09-23 11:14:05 -0400"]),
    ("2024-09-23 15:14:05 GET /index.html HTTP/1.1", ["2024-09-23 15:14:05"]),
    ("2024-09-23 15:14:05 -12 dB on channel 3", ["2024-09-23 15:14:05"]),
    ("2024-09-23 15:14:05,42,foo,bar", ["2024-09-23 15:14:05"]),
    ("Sep 23 15:27:40 EST-SRV01 sshd[2211]: Accepted", ["Sep 23 15:27:40"]),
    ("2024-09-23T15:14:05Zfoo and 2024-09-23T15:14:05Z.", ["2024-09-23T15:14:05Z"]),
    ("version 1.2.3 released, build 4.5.6.7 at noon", []),
    ("IP 203.0.113.7 port 51022 bytes=3221225472 id 0x80070005", []),
    ("at 10:30 PM we met; 3/4 of the users agreed; order 20240923 shipped", []),
    ("May 5 people attended the Mar 2024 review", []),
    ("slots 10-12 15:00 and 12-14 16:00", []),
    ("v2.3.4 10:00:00 and 10.0.0.15 10:00:00 and PM2.5 at 12:00 PM", []),
]


def main():
    out = sys.stdout
    # ── one value per format, each read the way its own format says ─────────────────────────────
    for text, reading in [
        ("1727104445", "unix-s"),
        ("1727104445123", "unix-ms"),
        ("1727104445123456", "unix-us"),
        ("1727104445123456789", "unix-ns"),
        ("133712345678901234", "filetime"),
        ("13371234567890123", "webkit"),
        ("748797245", "cocoa"),
        ("45558.5", "excel"),
    ]:
        n = float(text) if "." in text else int(text)
        out.write("format\t%s\t%s\t%s\n" % (text, reading, READ[reading](n)))
    ft = 133712345678901234
    out.write("format\t0x%016X\tfiletime\t%s\n" % (ft, READ["filetime"](ft)))
    for text in ["2024-09-23T20:44:05.123+05:30", "2024-09-23T15:14:05Z"]:
        t = dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
        frac = text.split(".")[1][:3] if "." in text else ""
        out.write("format\t%s\tiso8601\t%s\n" % (text, iso(int((t - EPOCH).total_seconds()), frac)))
    for text in ["Mon, 23 Sep 2024 11:14:05 -0400"]:
        t = email.utils.parsedate_to_datetime(text).astimezone(UTC)
        out.write("format\t%s\trfc2822\t%s\n" % (text, iso(int((t - EPOCH).total_seconds()))))
    # .NET's DateTime.Ticks, and Unix seconds as the registry and a program's header keep them, in hex
    ticks = (1727104445 + FROM_0001) * 10**7 + 1234567
    out.write("format\t%d\tdotnet\t%s\n" % (ticks, READ["dotnet"](ticks)))
    out.write("format\t0x%08X\tunix-s\t%s\n" % (1727104445, READ["unix-s"](1727104445)))

    # ── a bare number: every reading that lands in 1990-2040, never one picked silently ─────────
    for text in ["1727104445", "1727104445123", "133712345678901234", "748797245", "45558", str(ticks)]:
        n = int(text)
        found = []
        for name, read in FORMAT:
            try:
                utc = read(n)
            except (OverflowError, ValueError):
                continue
            if in_window(utc):
                found.append("%s=%s" % (name, utc))
        out.write("bare\t%s\t%s\n" % (text, " ".join(found)))

    # ── dates written as text ───────────────────────────────────────────────────────────────────
    for text, reading, fmt, frac, east in TEXT:
        out.write("format\t%s\t%s\t%s\n" % (text, reading, strp(text, fmt, frac, east)))
    # a certificate's UTCTime: RFC 5280 reads 50-99 as 1950-1999, not strptime's 69-99
    for text in ["240923151405Z", "990923151405Z", "550923151405Z", "240923204405+0530"]:
        century = "19" if int(text[:2]) >= 50 else "20"
        out.write("format\t%s\tx509\t%s\n" % (text, strp(century + text, "%Y%m%d%H%M%S%z")))
    for text, readings in BARE_TEXT:
        out.write("bare\t%s\t%s\n" % (text, " ".join("%s=%s" % (r, strp(text, f)) for r, f in readings)))
    for text, reading, fmt, abbr in ABBR:
        local = dt.datetime.strptime(text, fmt).replace(tzinfo=UTC)
        utcs = [iso(int((local - EPOCH).total_seconds()) - m * 60) for m in meanings(abbr, local.year)]
        out.write("format\t%s\t%s\t%s\n" % (text, reading, " ".join(utcs)))
    for now, rows in YEARLESS:
        out.write("now\t%s\n" % now)
        t_now = dt.datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        for text, reading, fmt, frac in rows:
            y = guess_year(t_now, cut(text, frac), fmt)
            out.write("format\t%s\t%s\t%s\n" % (text, reading, strp("%d %s" % (y, text), "%Y " + fmt, frac)))
    # a zone abbreviation on a date without a year: the year first, then what the name meant then
    text, fmt = "Sep 23 11:14:05.123 EDT", "%b %d %H:%M:%S EDT"
    y = guess_year(t_now, cut(text, "123"), fmt)
    local = dt.datetime.strptime("%d %s" % (y, cut(text, "123")), "%Y " + fmt).replace(tzinfo=UTC)
    out.write("format\t%s\tsyslog\t%s\n" % (text, " ".join(iso(int((local - EPOCH).total_seconds()) - m * 60, "123")
                                                          for m in meanings("EDT", y))))

    # ── zones: the place's own rules on that date, including the edges and the old rules ────────
    rows = [
        ("2024-09-23T15:14:05.123Z", ["America/New_York", "Australia/Sydney", "Australia/Brisbane",
                                      "Asia/Kolkata", "Europe/London", "UTC"]),
        # New York: spring forward and fall back, 2024
        ("2024-03-10T06:59:59Z", ["America/New_York"]), ("2024-03-10T07:00:00Z", ["America/New_York"]),
        ("2024-11-03T05:59:59Z", ["America/New_York"]), ("2024-11-03T06:00:00Z", ["America/New_York"]),
        # Sydney: daylight time starts in October and ends in April; Brisbane never moves
        ("2024-10-05T15:59:59Z", ["Australia/Sydney"]), ("2024-10-05T16:00:00Z", ["Australia/Sydney"]),
        ("2024-04-06T15:59:59Z", ["Australia/Sydney"]), ("2024-04-06T16:00:00Z", ["Australia/Sydney"]),
        ("2024-01-15T12:00:00Z", ["Australia/Sydney", "Australia/Brisbane", "America/New_York"]),
        ("2024-07-15T12:00:00Z", ["Australia/Sydney", "Australia/Brisbane", "America/New_York"]),
        # London: British Summer Time starts
        ("2024-03-31T00:59:59Z", ["Europe/London"]), ("2024-03-31T01:00:00Z", ["Europe/London"]),
        # the OLD rules: US daylight time began in April before 2007, Sydney's in late October before
        # 2008. An implementation that applies today's rules to every year gets these two wrong.
        ("2006-03-15T12:00:00Z", ["America/New_York"]),
        ("2007-10-15T00:00:00Z", ["Australia/Sydney"]),
    ]
    for utc, zones in rows:
        frac = utc[20:-1] if "." in utc else ""
        t = dt.datetime.strptime(utc[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        for z in zones:
            local = t.astimezone(zoneinfo.ZoneInfo(z))
            off = local.utcoffset()
            mins = int(off.total_seconds()) // 60
            sign = "+" if mins >= 0 else "-"
            out.write("zone\t%s\t%s\t%s%s\t%s%02d:%02d\t%s\n" % (
                utc, z, local.strftime("%Y-%m-%dT%H:%M:%S"), ("." + frac if frac else ""),
                sign, abs(mins) // 60, abs(mins) % 60, local.tzname()))

    # ── picking zones: a country code is every zone the IANA database lists for that country, in
    # its order (zone.tab, read here directly); a code and a city is that country's zones with that
    # city. UK is Britain (ISO's GB). ET, MT and PT are countries, not abbreviations.
    tab = [l.rstrip("\n").split("\t") for l in open("/usr/share/zoneinfo/zone.tab", encoding="utf-8")
           if l.strip() and not l.startswith("#")]

    def country(code):
        code = {"UK": "GB"}.get(code.upper(), code.upper())
        return [r[2] for r in tab if r[0] == code]

    def place(name):
        return name.rsplit("/", 1)[-1].replace("_", " ").lower()

    for spec in ["AU", "us", "uk", "ET", "MT", "PT", "IN", "NZ"]:
        out.write("pick\t%s\t%s\n" % (spec, " ".join(country(spec))))
    for spec in ["au sydney", "AU Lord Howe", "us/new york", "us indianapolis", "ca vancouver", "uk london",
                 "NZ_Chatham"]:
        city = spec[3:].replace("_", " ").lower()
        out.write("pick\t%s\t%s\n" % (spec, " ".join(z for z in country(spec[:2]) if place(z) == city)))
    # a code and a city that do not fit are a city: LA is Laos, and La Paz is in Bolivia; ST is Sao
    # Tome, and St Johns is in Canada
    for spec in ["la paz", "st_johns"]:
        city = spec.replace("_", " ")
        out.write("pick\t%s\t%s\n" % (spec, " ".join(n for n in sorted(zoneinfo.available_timezones()) if place(n) == city)))

    # ── timestamps in running text: which parts of a line are read ─────────────────────────────
    out.write("now\t2024-10-01T00:00:00Z\n")
    for line, found in FIND:
        assert "\t" not in line, line
        out.write("find\t%s\t%s\n" % (line, " | ".join(found)))

    # ── --from: times written with no zone, read in a zone (the now above still holds) ─────────
    t_now = dt.datetime(2024, 10, 1, tzinfo=UTC)
    for typed, zone, rows in FROM:
        out.write("from\t%s\t%s\n" % (typed, zone))
        for text, reading, fmt, frac in rows:
            out.write("format\t%s\t%s\t%s\n" % (text, reading, " ".join(local_in(text, fmt, frac, zone))))
        if typed == FROM_YEARLESS[0]:
            _, _, text, reading, fmt = FROM_YEARLESS
            y = guess_year(t_now, text, fmt)
            out.write("format\t%s\t%s\t%s\n" % (text, reading, " ".join(local_in("%d %s" % (y, text), "%Y " + fmt, "", zone))))
            out.write("format\t1727104445\tunix-s\t%s\n" % READ["unix-s"](1727104445))
    out.write("from\tutc\tUTC\n")


if __name__ == "__main__":
    main()
