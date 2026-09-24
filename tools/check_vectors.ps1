# check_vectors.ps1 -- tests/vectors.tsv checked by a second implementation: .NET, and the Windows
# time zone database it reads through ICU. tools/make_vectors.py wrote the file from Python and the
# IANA database; a value both agree on is trusted, one they disagree on is printed and fails the run.
# A date written as text is read here by .NET's own ParseExact, with .NET's patterns for its reading,
# and .NET works out the year of a date written without one by the same rule, on its own.
# Not checked here, and said so at the end: dates with a zone abbreviation (EDT, IST -- .NET has none,
# only Python's IANA data), which parts of a line are timestamps (find rows: tzdig's own rule, written
# by hand), and which country a zone belongs to (.NET has no country data; a pick row is checked only
# for every zone it names being a zone .NET knows -- a misspelling, not a zone under the wrong country).
#
#   pwsh tools/check_vectors.ps1
# PowerShell 7 only: Windows PowerShell 5.1 runs on .NET Framework, which knows no IANA zone names.
param([string]$Vectors = (Join-Path $PSScriptRoot '..\tests\vectors.tsv'))
$ErrorActionPreference = 'Stop'
$inv = [Globalization.CultureInfo]::InvariantCulture
$styles = [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AllowWhiteSpaces
$unix = [DateTime]::new(1970, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
$y1601 = [DateTime]::new(1601, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
$y2001 = [DateTime]::new(2001, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
$lo = [DateTime]::new(1990, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
$hi = [DateTime]::new(2041, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
$now = $null

# a DateTime to the second, then exactly the fraction digits the input carried
function Iso([DateTime]$t, [string]$frac) {
    $s = $t.ToString('yyyy-MM-ddTHH:mm:ss', $inv)
    if ($frac) { $s += '.' + $frac }
    return $s + 'Z'
}

# .NET's patterns for each way a date is written as text, the fraction of a second cut out first
# (.NET reads no more than 7 digits of one); a date with no zone is UTC
$patterns = @{
    'iso8601'    = @('yyyy-MM-dd HH:mm:ss zzz', 'yyyy-MM-ddTHH:mm:ssK', 'yyyy-MM-dd HH:mm:ss', 'yyyy-MM-dd HH:mm:ssK',
                     "yyyy-MM-dd HH:mm:ss zzz 'UTC'", "yyyy-MM-ddTHH:mm:sszzz'[Asia/Kolkata]'", 'yyyy-MM-dd HH:mm:sszz',
                     "yyyy-MM-dd HH:mm:ss 'UTC'", 'yyyy-MM-ddTHH:mm', "yyyyMMdd'T'HHmmssK", "yyyyMMdd'T'HHmmsszzz",
                     'yyyy-MM-dd_HH-mm-ss')
    'ldap'       = @('yyyyMMddHHmmssK', 'yyyyMMddHHmmsszzz')
    'x509'       = @('yyMMddHHmmssK')
    'compact'    = @('yyyyMMddHHmmss', 'yyyyMMdd_HHmmss', 'yyyyMMdd-HHmmss')
    'ymd'        = @('yyyy/M/d H:mm:ss', 'yyyy.MM.dd HH:mm:ss')
    'mdy'        = @('M/d/yyyy h:mm:ss tt', 'M/d/yy h:mm:ss tt', 'M/d/yyyy, h:mm:ss tt', 'M/d/yy,H:mm:ss', 'M/d/yyyy h:mm tt',
                     'M/d/yyyy H:mm', 'M-d-yyyy H:mm:ss')
    'dmy'        = @('d/M/yyyy H:mm:ss', 'd.M.yyyy H:mm:ss', 'd-M-yyyy H:mm', 'd/M/yyyy hh:mm tt', 'd/M/yyyy H:mm',
                     'd-M-yyyy H:mm:ss')
    'clf'        = @('dd/MMM/yyyy:HH:mm:ss zzz')
    'rfc2822'    = @("ddd, dd MMM yyyy HH:mm:ss zzz '(EDT)'", "dd MMM yyyy HH:mm:ss 'GMT'", 'ddd, dd MMM yyyy HH:mm:ss zzz')
    'month-name' = @('dd MMM yyyy HH:mm:ss', 'MMM d, yyyy h:mm:ss tt', "MMMM d, yyyy 'at' h:mm:ss tt",
                     "MMM d, yyyy '@' HH:mm:ss", "MMM'.' d, yyyy HH:mm:ss", 'dd-MMM-yyyy HH:mm:ss', 'dd-MMM-yy hh.mm.ss tt',
                     'dddd, MMMM d, yyyy h:mm:ss tt', 'dddd, d MMMM yyyy h:mm:ss tt', 'MMM d yyyy HH:mm:ss', 'ddMMMyyyy HH:mm:ss',
                     'MMM d yyyy h:mmtt', 'yyyy-MMM-dd HH:mm:ss', "ddd MMM dd yyyy HH:mm:ss 'GMT'zzz '(Eastern Daylight Time)'")
    'ctime'      = @('ddd MMM d HH:mm:ss yyyy', "ddd MMM d HH:mm:ss 'UTC' yyyy", "MMM d HH:mm:ss yyyy 'GMT'",
                     'ddd MMM d HH:mm:ss yyyy zzz')
    'syslog'     = @('MMM d HH:mm:ss')
    'klog'       = @("'I'MMdd HH:mm:ss")
    'logcat'     = @('MM-dd HH:mm:ss')
}
$yearless = @('syslog', 'klog', 'logcat')
# the zone abbreviations the file's dates are written with; parenthesised, one only repeats an offset
$abbr = '(?<![(\w])(EDT|EST|CDT|CST|MDT|MST|PDT|PST|IST|AST|SGT|AEST|AEDT|BST|MSD|MSK)(?![)\w])'

# a date written as text, read the .NET way; $null when no pattern of that reading fits
function Read-Text([string]$reading, [string]$text) {
    $frac = ''
    $m = [regex]::Match($text, '(?<=\d?\d[:.\-]\d\d[:.\-]\d\d|\d{14}|T\d{6})[.,](\d+)')
    if ($m.Success) { $frac = $m.Groups[1].Value; $text = $text.Remove($m.Index, $m.Length) }
    if ($reading -eq 'iso8601' -and $text -match '^(\d{4})-W(\d\d)-(\d)T(\d\d):(\d\d):(\d\d)Z$') {
        $d = [Globalization.ISOWeek]::ToDateTime([int]$Matches[1], [int]$Matches[2], [DayOfWeek]([int]$Matches[3] % 7))
        return Iso ($d.AddHours([int]$Matches[4]).AddMinutes([int]$Matches[5]).AddSeconds([int]$Matches[6])) $frac
    }
    if ($reading -eq 'iso8601' -and $text -match '^(\d{4})-(\d{3})T(\d\d):(\d\d):(\d\d)Z$') {
        $d = [DateTime]::new([int]$Matches[1], 1, 1).AddDays([int]$Matches[2] - 1)
        return Iso ($d.AddHours([int]$Matches[3]).AddMinutes([int]$Matches[4]).AddSeconds([int]$Matches[5])) $frac
    }
    $o = [DateTimeOffset]::MinValue
    if ($reading -in $yearless) {
        # the latest year in which the date is at most two days after now, as tzdig reads one
        $p = [string[]]($patterns[$reading] | ForEach-Object { "yyyy $_" })
        if (-not [DateTimeOffset]::TryParseExact("2000 $text", $p, $inv, $styles, [ref]$o)) { return $null }
        $t = $o.UtcDateTime
        for ($y = $now.Year; $y -gt $now.Year - 8; $y--) {
            if ($t.Month -eq 2 -and $t.Day -eq 29 -and -not [DateTime]::IsLeapYear($y)) { continue }
            $c = [DateTime]::new($y, $t.Month, $t.Day, $t.Hour, $t.Minute, $t.Second, [DateTimeKind]::Utc)
            if (($c - $now).TotalSeconds -le 172800) { return Iso $c $frac }
        }
        return $null
    }
    if (-not [DateTimeOffset]::TryParseExact($text, [string[]]$patterns[$reading], $inv, $styles, [ref]$o)) { return $null }
    return Iso $o.UtcDateTime $frac
}

# one reading of one input, the .NET way; $null when .NET cannot represent it
function Read-As([string]$reading, [string]$text) {
    try {
        if ($patterns.ContainsKey($reading)) { return Read-Text $reading $text }
        switch ($reading) {
            'unix-s'   { $n = if ($text -like '0x*') { [Convert]::ToInt64($text.Substring(2), 16) } else { [long]$text }
                         return Iso ([DateTimeOffset]::FromUnixTimeSeconds($n).UtcDateTime) '' }
            'unix-ms'  { $n = [long]$text; return Iso ([DateTimeOffset]::FromUnixTimeMilliseconds($n).UtcDateTime) ('{0:D3}' -f ($n % 1000)) }
            'unix-us'  { $n = [long]$text; return Iso ($unix.AddTicks(($n - $n % 1000000) * 10)) ('{0:D6}' -f ($n % 1000000)) }
            'unix-ns'  { $n = [decimal]$text; $s = [long][Math]::Floor($n / 1e9); return Iso ($unix.AddSeconds($s)) ('{0:D9}' -f [long]($n - [decimal]$s * 1e9)) }
            'filetime' { $n = if ($text -like '0x*') { [Convert]::ToInt64($text.Substring(2), 16) } else { [long]$text }
                         $t = [DateTime]::FromFileTimeUtc($n); return Iso $t ('{0:D7}' -f ($t.Ticks % 10000000)) }
            'webkit'   { $n = [long]$text; return Iso ($y1601.AddTicks(($n - $n % 1000000) * 10)) ('{0:D6}' -f ($n % 1000000)) }
            'cocoa'    { return Iso ($y2001.AddSeconds([long]$text)) '' }
            'excel'    { return Iso ([DateTime]::SpecifyKind([DateTime]::FromOADate([double]::Parse($text, $inv)), 'Utc')) '' }
            'dotnet'   { $t = [DateTime]::new([long]$text, [DateTimeKind]::Utc); return Iso $t ('{0:D7}' -f ($t.Ticks % 10000000)) }
        }
    } catch { return $null }
}

$agree = 0; $bad = @(); $skipped = @{ abbreviation = 0; find = 0 }
foreach ($line in Get-Content -LiteralPath $Vectors -Encoding UTF8) {
    if (-not $line.Trim()) { continue }
    $f = $line -split "`t"
    switch ($f[0]) {
        'now' {
            $now = [DateTime]::SpecifyKind([DateTime]::ParseExact($f[1], "yyyy-MM-dd'T'HH:mm:ss'Z'", $inv), 'Utc')
        }
        'format' {
            if ($f[1] -match $abbr) { $skipped.abbreviation++; continue }
            $got = Read-As $f[2] $f[1]
            if ($got -eq $f[3]) { $agree++ } else { $bad += "format $($f[1]) as $($f[2]): python $($f[3]), .NET $got" }
        }
        'bare' {
            if ($f[1] -match '^\d+$') {
                # .NET decides on its own which readings of a number land in 1990-2040; the list must be the same
                $mine = @()
                foreach ($r in 'unix-s', 'unix-ms', 'unix-us', 'unix-ns', 'filetime', 'webkit', 'cocoa', 'excel', 'dotnet') {
                    $u = Read-As $r $f[1]
                    if (-not $u) { continue }
                    $t = [DateTime]::ParseExact($u.Substring(0, 19), 'yyyy-MM-ddTHH:mm:ss', $inv)
                    if ($t -ge $lo -and $t -lt $hi) { $mine += "$r=$u" }
                }
                if (($mine -join ' ') -eq $f[2]) { $agree++ } else { $bad += "bare $($f[1]): python [$($f[2])], .NET [$($mine -join ' ')]" }
            } else {
                # a date that reads more than one way: each reading, read the .NET way
                $mine = @($f[2] -split ' ' | ForEach-Object { $r = $_.Split('=')[0]; "$r=$(Read-As $r $f[1])" })
                if (($mine -join ' ') -eq $f[2]) { $agree++ } else { $bad += "bare $($f[1]): python [$($f[2])], .NET [$($mine -join ' ')]" }
            }
        }
        'zone' {
            $utc = [DateTime]::SpecifyKind([DateTime]::ParseExact($f[1].Substring(0, 19), 'yyyy-MM-ddTHH:mm:ss', $inv), 'Utc')
            $tz = [TimeZoneInfo]::FindSystemTimeZoneById($f[2])
            $local = [TimeZoneInfo]::ConvertTimeFromUtc($utc, $tz)
            $frac = if ($f[1] -match '\.(\d+)Z$') { '.' + $Matches[1] } else { '' }
            $off = $tz.GetUtcOffset($utc)
            $offs = '{0}{1:D2}:{2:D2}' -f ($(if ($off -lt [TimeSpan]::Zero) { '-' } else { '+' })), [Math]::Abs($off.Hours), [Math]::Abs($off.Minutes)
            $got = $local.ToString('yyyy-MM-ddTHH:mm:ss', $inv) + $frac
            if ($got -eq $f[3] -and $offs -eq $f[4]) { $agree++ } else { $bad += "zone $($f[1]) $($f[2]): python $($f[3]) $($f[4]), .NET $got $offs" }
        }
        'pick' {
            $unknown = @($f[2] -split ' ' | Where-Object { $z = $null; -not $_ -or -not [TimeZoneInfo]::TryFindSystemTimeZoneById($_, [ref]$z) })
            if (-not $unknown.Count) { $agree++ } else { $bad += "pick '$($f[1])': .NET has no zone called $($unknown -join ', ')" }
        }
        'find' { $skipped.find++ }
    }
}
"python and .NET agree on $agree rows (not checked by .NET: $($skipped.abbreviation) with a zone abbreviation, $($skipped.find) find rows)"
if ($bad.Count) { "DISAGREE on $($bad.Count):"; $bad | ForEach-Object { "  $_" }; exit 1 }
