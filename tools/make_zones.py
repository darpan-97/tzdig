#!/usr/bin/env python3
"""make_zones.py -- every IANA time zone, as data `tzdig` reads without asking the operating system.

Why data and not the system's time zone API: `tzdig` is built for several targets (a native binary,
JavaScript, wasm), and each host's time zone support differs -- or, in a browser build, is out of
reach. A table generated once from the IANA database gives every build the same answer.

Where the numbers come from: the compiled IANA files (TZif, RFC 8536) under /usr/share/zoneinfo.
Their transitions are exact. After a file's last listed transition a zone follows a rule (the POSIX
TZ string at the end of the file); those later transitions come from Python's zoneinfo, which applies
that rule. Before writing anything, every zone is checked against zoneinfo at each of its transitions
and once a month for the whole range; one disagreement and nothing is written.

Run on Linux or WSL:
    python3 tools/make_zones.py > src/zones.nitro

The range is 1970-01-01 to 2070-01-01. Outside it `tzdig` still gives UTC, and says it has no zone
rules for that date rather than guessing.
"""
import datetime as dt
import os
import struct
import sys
import zlib
import zoneinfo

ZONEINFO = "/usr/share/zoneinfo"
UTC = dt.timezone.utc
LO = int(dt.datetime(1970, 1, 1, tzinfo=UTC).timestamp())
HI = int(dt.datetime(2070, 1, 1, tzinfo=UTC).timestamp())
PART = 64                                    # stores per generated function: see main()


def read_tzif(path):
    """the 64-bit part of a TZif file: transition times, their types, the types, the footer rule"""
    b = open(path, "rb").read()
    if b[:4] != b"TZif":
        raise ValueError("not a TZif file: " + path)

    def counts(at):
        return struct.unpack(">6l", b[at + 20:at + 44])

    isut, isstd, leap, timecnt, typecnt, charcnt = counts(0)
    if b[4] < ord("2"):
        raise ValueError("TZif version 1 has no 64-bit data: " + path)
    at = 44 + timecnt * 5 + typecnt * 6 + charcnt + leap * 8 + isstd + isut   # skip the 32-bit block
    isut, isstd, leap, timecnt, typecnt, charcnt = counts(at)
    p = at + 44
    times = struct.unpack(">%dq" % timecnt, b[p:p + 8 * timecnt]); p += 8 * timecnt
    idx = list(b[p:p + timecnt]); p += timecnt
    raw = [struct.unpack(">lBB", b[p + 6 * i:p + 6 * i + 6]) for i in range(typecnt)]; p += 6 * typecnt
    chars = b[p:p + charcnt]; p += charcnt + leap * 12 + isstd + isut
    footer = b[p:].split(b"\n")[1].decode() if b[p:p + 1] == b"\n" else ""

    def abbr(i):
        return chars[i:chars.index(b"\0", i)].decode()

    types = [(off, dst, abbr(ai)) for off, dst, ai in raw]
    return list(times), idx, types, footer


def key_at(zi, t):
    """(offset seconds, 1 if daylight time, abbreviation) at UTC second t, by zoneinfo"""
    x = dt.datetime.fromtimestamp(t, UTC).astimezone(zi)
    return (int(x.utcoffset().total_seconds()), 1 if x.dst() else 0, x.tzname())


def history(name):
    """the key in force at LO, and every change of key in (LO, HI) as (utc second, key)"""
    times, idx, types, footer = read_tzif(os.path.join(ZONEINFO, name))
    zi = zoneinfo.ZoneInfo(name)
    # the type in force at LO: the last transition at or before it, else type 0 (RFC 8536 3.2)
    first = types[0]
    for t, i in zip(times, idx):
        if t <= LO:
            first = types[i]
    changes = [(t, types[i]) for t, i in zip(times, idx) if LO < t < HI]
    # after the file's last transition, the footer rule: find its changes day by day, then to the second
    t = max([LO] + [x for x in times if x < HI])
    prev = key_at(zi, t)
    while t < HI:
        n = min(t + 86400, HI - 1)
        k = key_at(zi, n)
        if k != prev:
            a, z = t, n
            while z - a > 1:
                m = (a + z) // 2
                if key_at(zi, m) == prev:
                    a = m
                else:
                    z = m
            changes.append((z, k))
            prev = k
        if n == HI - 1:
            break
        t = n
    # keep only real changes: a TZif file may list a transition that changes nothing we print
    out, cur = [], first
    for t, k in sorted(changes):
        if k != cur:
            out.append((t, k))
            cur = k
    return first, out


def word(v):
    """a 32-bit value as nitro source: -2147483648 is written as arithmetic, since the literal
    2147483648 does not fit before the minus sign applies"""
    return "0 - 2147483647 - 1" if v == -(1 << 31) else str(v)


def lookup(first, changes, t):
    k = first
    for when, kk in changes:
        if when <= t:
            k = kk
        else:
            break
    return k


def check(name, first, changes):
    zi = zoneinfo.ZoneInfo(name)
    probes = [LO] + [t + d for t, _ in changes for d in (-1, 0)]
    probes += range(LO, HI, 30 * 86400)
    for t in probes:
        if not (LO <= t < HI):
            continue
        mine, theirs = lookup(first, changes, t), key_at(zi, t)
        if mine != theirs:
            sys.exit("make_zones: %s at %d: table %r, zoneinfo %r -- nothing written" % (name, t, mine, theirs))


def countries(names):
    """ISO 3166 alpha-2 code -> (country name, [(zone, description)]), from iso3166.tab and zone.tab:
    the IANA database's own list of which zones each country uses, one country per zone"""
    def tab(f):
        return [l.rstrip("\n").split("\t") for l in open(os.path.join(ZONEINFO, f), encoding="utf-8")
                if l.strip() and not l.startswith("#")]
    names = set(names)
    out = {code: (name, []) for code, name in tab("iso3166.tab")}
    for row in tab("zone.tab"):
        code, zone = row[0], row[2]
        note = row[3] if len(row) > 3 else ""
        if code not in out or zone not in names or "|" in note or "=" in note or len(code) != 2 or not code.isupper():
            sys.exit("make_zones: zone.tab row %r does not fit -- nothing written" % (row,))
        out[code][1].append((zone, note))
    return {c: v for c, v in out.items() if v[1]}


def main():
    version = open(os.path.join(ZONEINFO, "tzdata.zi")).readline().split()[-1]
    names = sorted(zoneinfo.available_timezones())
    cc = countries(names)
    code_of = {z: c for c, (_, zs) in cc.items() for z, _ in zs}
    records, index, ids = [], {}, []
    for name in names:
        first, changes = history(name)
        check(name, first, changes)
        types = [first] + [k for _, k in changes]
        uniq = []
        for k in types:
            if k not in uniq:
                uniq.append(k)
        rec = ",".join("%d:%d:%s" % k for k in uniq) + "|" + str(uniq.index(first)) + "|"
        last, parts = LO, []
        for t, k in changes:
            parts.append("%d:%d" % (t - last, uniq.index(k)))
            last = t
        rec += ",".join(parts)
        if rec not in index:
            index[rec] = len(records)
            records.append(rec)
        ids.append((name, index[rec]))
    # THE TABLE IS SHIPPED COMPRESSED, AS WORDS. nitro builds a string literal byte by byte in code
    # (three instructions a byte), so the plain 290 KB table became 900,000 instructions and 88 MB
    # of C that clang could not compile. Raw DEFLATE shrinks it about 12 times, lib/inflate unpacks
    # it at run time, and each 4 bytes is one store: about 28,000 instructions for every zone and
    # every country.
    text = ("%d %d %d\n" % (len(ids), len(records), len(cc))
            + "".join("%s %d %s\n" % (n, r, code_of.get(n, "-")) for n, r in ids)
            + "".join(r + "\n" for r in records)
            + "".join("%s|%s|%s\n" % (c, cc[c][0], "|".join("%s=%s" % zn for zn in cc[c][1])) for c in sorted(cc))
            ).encode()
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = c.compress(text) + c.flush()
    if zlib.decompress(packed, -15) != text:
        sys.exit("make_zones: the compressed table does not decompress to itself -- nothing written")
    crc = zlib.crc32(text)
    words = packed + b"\0" * (-len(packed) % 4)
    out = sys.stdout
    out.write("module zones\n\n")
    out.write("# GENERATED by tools/make_zones.py from the IANA time zone database, version %s. Do not edit.\n" % version)
    out.write("#\n# zones_unpack_into(p) writes the table, raw DEFLATE, at p; lib/inflate turns it back into text:\n")
    out.write("#   <names> <records> <countries>\n")
    out.write("#   <name> <record number> <country code, or ->   one line per zone name\n")
    out.write("#   <types>|<type at 1970-01-01>|<changes>    one line per record; names with one history share it\n")
    out.write("#   <ISO 3166 alpha-2 code>|<country>|<zone>=<description>|...   one line per country, from zone.tab\n")
    out.write("#   types: offset seconds:1 if daylight time:abbreviation, comma-separated, numbered from 0\n")
    out.write("#   changes: seconds since the previous change (the first: since 1970-01-01):type, comma-separated\n")
    out.write("# Range 1970-01-01 to 2070-01-01 UTC. zones_text_crc32 is zlib's CRC-32 of the text.\n\n")
    out.write('pub fn zones_version(): return "%s"\n\n' % version)
    out.write("pub fn zones_first_second() -> i64: return i64(%d)\n" % LO)
    out.write("pub fn zones_end_second() -> i64: return i64(%d)\n\n" % HI)
    out.write("pub fn zones_text_size(): return %d\n" % len(text))
    out.write("pub fn zones_packed_size(): return %d\n" % len(packed))
    out.write("pub fn zones_text_crc32(): return %s\n\n" % word(crc - (1 << 32) if crc >= (1 << 31) else crc))
    # THE STORES ARE SPLIT INTO FUNCTIONS OF 64. As one function of 6,330 stores, clang -O2 spent
    # 35 s on it (the rest of `tzdig` takes 4 s); in functions of 64 it takes 3 s. The cost grows
    # faster than the function does, so the size of each function is what matters, not the total.
    stores = ["    store(p + %d, %s)\n" % (i, word(int.from_bytes(words[i:i + 4], "little", signed=True)))
              for i in range(0, len(words), 4)]
    parts = [stores[i:i + PART] for i in range(0, len(stores), PART)]
    for k, part in enumerate(parts):
        out.write("fn zones_part_%d(p):\n" % k)
        out.write("".join(part))
        out.write("    return 0\n\n")
    out.write("pub fn zones_unpack_into(p):\n")
    for k in range(len(parts)):
        out.write("    zones_part_%d(p)\n" % k)
    out.write("    return 0\n")
    sys.stderr.write("make_zones: IANA %s, %d names, %d distinct records, %d countries, %d bytes of text, %d packed\n" % (
        version, len(ids), len(records), len(cc), len(text), len(packed)))


if __name__ == "__main__":
    main()
