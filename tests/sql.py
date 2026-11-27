"""A pod in SQLite, as queries/statements.sql lays it out: the loader that fills it from an Oxigraph store, the functions a
`.sql` calls where SQLite has no answer of its own, and the comparison of the rows a query gives with the rows wanted,
each term as N-Triples. What a runtime's SQLite gives for each `.sql` is compared with its `.rq` by the runtime's own
check, in the `compatibility` job, not here."""

import hashlib
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import cache
from urllib.parse import quote

import pyoxigraph

from contract import QUERIES

SCHEMA = QUERIES / "statements.sql"
XSD = "http://www.w3.org/2001/XMLSchema#"
LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
BLANK, IRI, LITERAL = 1, 2, 3


@dataclass(frozen=True, order=True)
class Term:
    """An RDF term as SPARQL tells terms apart: its kind, its IRI, blank node label or lexical form, and a literal's
    datatype and language."""
    kind: int
    value: str
    datatype: str | None = None
    lang: str | None = None

    def __str__(self):
        if self.kind == IRI:
            return f"<{self.value}>"
        if self.kind == BLANK:
            return f"_:{self.value}"
        text = '"' + "".join(escaped(c) for c in self.value) + '"'
        if self.lang:
            return f"{text}@{self.lang}"
        return text if self.datatype == XSD + "string" else f"{text}^^<{self.datatype}>"


ESCAPED = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r", '"': '\\"', "\\": "\\\\"}


def escaped(character):
    """A character of a literal as Oxigraph's N-Triples writes it: a short escape where there is one, any other control
    character as \\u and four upper-case hexadecimal digits, and every other character as itself."""
    if character in ESCAPED:
        return ESCAPED[character]
    return f"\\u{ord(character):04X}" if ord(character) < 0x20 or ord(character) == 0x7F else character
UNESCAPED = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}
NT = re.compile(r'<([^>]*)>|_:(\S+)|"((?:[^"\\]|\\.)*)"(?:@([A-Za-z0-9-]+)|\^\^<([^>]*)>)?', re.DOTALL)


def parsed(nt):
    """The term an N-Triples term's text writes, or None for None."""
    if nt is None:
        return None
    match = NT.fullmatch(nt) if isinstance(nt, str) else None
    if not match:
        raise ValueError(f"{nt!r} is no N-Triples term")
    iri, blank, text, lang, datatype = match.groups()
    if iri is not None:
        return Term(IRI, unescaped(iri))
    if blank is not None:
        return Term(BLANK, blank)
    return Term(LITERAL, unescaped(text), LANG_STRING if lang else datatype or XSD + "string", lang)


def unescaped(text):
    return re.sub(r"\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)",
                  lambda m: chr(int(m.group(1)[1:], 16)) if len(m.group(1)) > 1 else UNESCAPED[m.group(1)], text)


def from_oxigraph(term):
    if isinstance(term, pyoxigraph.NamedNode):
        return Term(IRI, term.value)
    if isinstance(term, pyoxigraph.BlankNode):
        return Term(BLANK, term.value)
    if term.language:
        return Term(LITERAL, term.value, LANG_STRING, term.language)
    return Term(LITERAL, term.value, term.datatype.value)


# The calendar keys

DATE_TIME = re.compile(r"(-?[0-9]{4,})-([0-9][0-9])-([0-9][0-9])T([0-9][0-9]):([0-9][0-9]):([0-9][0-9])(?:\.([0-9]+))?(Z|[+-][0-9][0-9]:[0-9][0-9])?")
DATE = re.compile(r"(-?[0-9]{4,})-([0-9][0-9])-([0-9][0-9])(Z|[+-][0-9][0-9]:[0-9][0-9])?")
GYEAR = re.compile(r"(-?[0-9]{4,})(Z|[+-][0-9][0-9]:[0-9][0-9])?")
GYEAR_MONTH = re.compile(r"(-?[0-9]{4,})-([0-9][0-9])(Z|[+-][0-9][0-9]:[0-9][0-9])?")
SCALE = 10 ** 18
FOURTEEN_HOURS = 14 * 3600 * SCALE


def days_from_civil(year, month, day):
    """Days from 1970-01-01 to the day of the proleptic Gregorian calendar."""
    year -= month <= 2
    era = year // 400
    of_era = year - era * 400
    of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    return era * 146097 + of_era * 365 + of_era // 4 - of_era // 100 + of_year - 719468


def civil_from_days(days):
    days += 719468
    era = days // 146097
    of_era = days - era * 146097
    of_year_era = (of_era - of_era // 1460 + of_era // 36524 - of_era // 146096) // 365
    of_year = of_era - (365 * of_year_era + of_year_era // 4 - of_year_era // 100)
    shifted = (5 * of_year + 2) // 153
    day = of_year - (153 * shifted + 2) // 5 + 1
    month = shifted + (3 if shifted < 10 else -9)
    return of_year_era + era * 400 + (month <= 2), month, day


def days_in(year, month):
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]


def zone_minutes(zone):
    if zone is None:
        return None
    if zone == "Z":
        return 0
    hours, minutes = int(zone[1:3]), int(zone[4:6])
    if hours > 14 or minutes > 59 or (hours == 14 and minutes):
        raise ValueError(zone)
    return (-1 if zone[0] == "-" else 1) * (hours * 60 + minutes)


@dataclass(frozen=True)
class Moment:
    """A point on the timeline in units of 10^-18 s from 1970-01-01T00:00:00Z, a value with no zone read as if in UTC,
    and whether it had one."""
    at: int
    zoned: bool


def moment(datatype, lexical):
    """The moment an xsd:dateTime, xsd:date, xsd:gYear or xsd:gYearMonth value starts, or None for a lexical form
    Oxigraph holds ill-typed."""
    try:
        if datatype == XSD + "dateTime" and (m := DATE_TIME.fullmatch(lexical)):
            year, month, day, hour, minute, second, fraction, zone = m.groups()
            year, month, day, hour, minute, second = map(int, (year, month, day, hour, minute, second))
            fraction = fraction or ""
            if (len(fraction) > 18 or not 1 <= month <= 12 or not 1 <= day <= days_in(year, month) or minute > 59
                    or second > 59 or hour > 24 or (hour == 24 and (minute or second or fraction.strip("0")))):
                return None
            seconds = days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second
            fraction_scaled = int(fraction.ljust(18, "0") or "0")
        elif datatype in (XSD + "date", XSD + "gYearMonth", XSD + "gYear"):
            pattern = {XSD + "date": DATE, XSD + "gYearMonth": GYEAR_MONTH, XSD + "gYear": GYEAR}[datatype]
            if not (m := pattern.fullmatch(lexical)):
                return None
            *parts, zone = m.groups()
            year, month, day = (list(map(int, parts)) + [1, 1])[:3]
            if not 1 <= month <= 12 or not 1 <= day <= days_in(year, month):
                return None
            seconds, fraction_scaled = days_from_civil(year, month, day) * 86400, 0
        else:
            return None
        offset = zone_minutes(zone)
    except ValueError:
        return None
    return Moment((seconds - (offset or 0) * 60) * SCALE + fraction_scaled, offset is not None)


def instant_key(term):
    """A valid xsd:dateTime's or xsd:date's start in UTC, a value with no zone read as if in UTC, written
    YYYY-MM-DDThh:mm:ss and eighteen fractional digits, so text order is time order; None for any other term, and for a
    year before 1 or after 9999."""
    if term.kind != LITERAL or term.datatype not in (XSD + "dateTime", XSD + "date"):
        return None
    found = moment(term.datatype, term.value)
    if found is None:
        return None
    seconds, fraction = divmod(found.at, SCALE)
    days, seconds = divmod(seconds, 86400)
    year, month, day = civil_from_days(days)
    if not 1 <= year <= 9999:
        return None
    return (f"{year:04d}-{month:02d}-{day:02d}T{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
            f".{fraction:018d}")


def day_key(term):
    """A valid xsd:dateTime's or xsd:date's calendar day as its lexical form writes it, YYYY-MM-DD, its zone ignored;
    None for any other term."""
    if term.kind != LITERAL or term.datatype not in (XSD + "dateTime", XSD + "date"):
        return None
    if moment(term.datatype, term.value) is None:
        return None
    return (DATE_TIME if term.datatype == XSD + "dateTime" else DATE).fullmatch(term.value).expand(r"\1-\2-\3")


# The functions a `.sql` calls

ESCAPED_ALIKE = set(r"\|.-^?*+{}()[]$nrt")
QUANTIFIER = re.compile(r"\{[0-9]+(,[0-9]*)?\}")
# What Rust's regex reads as white space under the x flag: Unicode's White_Space property
WHITE_SPACE = frozenset(map(chr, (*range(0x09, 0x0E), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029,
                                  0x202F, 0x205F, 0x3000)))
CASE_APART = {"İ", "ı"}


def refused(text):
    """Why the text has a character that Python's Unicode does not assign and Oxigraph's newer one may, or None."""
    found = next((c for c in text if unicodedata.category(c) == "Cn"), None)
    return None if found is None else f"U+{ord(found):04X}, which this Python's Unicode does not assign"


def python_pattern(pattern, flags, text=""):
    """A pattern Oxigraph's regular expressions read, as Python's `re` reads it: outside a class, `$` is the end of the
    text alone, as it is in Rust's regex unless the m flag is given. Whatever the vectors leave out, where the two may
    read a pattern apart, is refused with ValueError: an escape but of a metacharacter, n, r or t; a group opened with
    `(?` but `(?:`; a quantifier after a quantifier, so a lazy or possessive one; a `{` or `}` that is no quantifier; a
    `[` inside a class, as a POSIX class has, or `&&`, `--` or `~~` there; under the x flag a `#`, white space in a
    class, or non-ASCII white space; and, under the i flag, a dotted or dotless I, which Python's case-insensitive match equates with i and Rust's
    does not, or a character Python's Unicode does not assign."""
    if "i" in flags:
        if CASE_APART & set(pattern + text):
            raise ValueError(f"{pattern!r} under the i flag meets a dotted or dotless I, which no vector covers")
        if why := refused(pattern + text):
            raise ValueError(f"{pattern!r} under the i flag meets {why}")
    if "q" in flags:
        return re.escape(pattern)
    if "x" in flags and "#" in pattern:
        raise ValueError(f"{pattern!r} has a # under the x flag, which no vector covers")
    out, in_class, quantified, i = [], False, False, 0
    while i < len(pattern):
        c, after = pattern[i], pattern[i + 1:i + 2]
        if c == "\\":
            if after not in ESCAPED_ALIKE or not after:
                raise ValueError(f"{pattern!r} uses an escape no vector covers")
            out.append(pattern[i:i + 2])
            i, quantified = i + 2, False
            continue
        if in_class:
            if c == "[" or pattern[i:i + 2] in ("&&", "--", "~~") or ("x" in flags and c in WHITE_SPACE):
                raise ValueError(f"{pattern!r} has a class no vector covers")
            in_class = c != "]"
            out.append(c)
            i += 1
            continue
        if "x" in flags and c in WHITE_SPACE:
            if c > "\x7f":
                raise ValueError(f"{pattern!r} has white space {c!r} outside a class under the x flag, which no vector covers")
            out.append(c)
            i += 1
            continue
        if c == "[":
            opening = re.match(r"\^?\]?", pattern[i + 1:]).group()
            out.append(c + opening)
            i, in_class, quantified = i + 1 + len(opening), True, False
            continue
        if c == "(" and after == "?":
            if pattern[i + 2:i + 3] != ":":
                raise ValueError(f"{pattern!r} opens a group with (? but (?:, which no vector covers")
            out.append("(?:")
            i, quantified = i + 3, False
            continue
        quantifier = QUANTIFIER.match(pattern, i) if c == "{" else None
        if c in "{}" and not quantifier:
            raise ValueError(f"{pattern!r} has a {c} that is no quantifier, which no vector covers")
        if c in "*+?" or quantifier:
            if quantified:
                raise ValueError(f"{pattern!r} has a quantifier after a quantifier, which no vector covers")
            token = quantifier.group() if quantifier else c
            out.append(token)
            i, quantified = i + len(token), True
            continue
        out.append(r"\Z" if c == "$" and "m" not in flags else c)
        i, quantified = i + 1, False
    return "".join(out)


REFERENCE = re.compile(r"\$(?:\$|\{([A-Za-z0-9_]+)\}|([A-Za-z0-9_]+))?")


def expanded(replacement, match):
    """The replacement with each `$name`, `${name}` and `$$` read as Rust's regex reads them: a name of digits is a
    group's number, a group the match does not have is empty, `$$` is `$`, and a `$` before anything else is itself."""
    def group(found):
        if found.group() == "$$":
            return "$"
        name = found.group(1) or found.group(2)
        if name is None:
            return "$"
        try:
            value = match.group(int(name) if name.isdigit() else name)
        except IndexError:
            return ""
        return value or ""

    return REFERENCE.sub(group, replacement)


def sparql_replace(text, pattern, replacement, flags=""):
    """SPARQL's REPLACE as Oxigraph gives it, over strings: every match of the pattern, read with the flags (s, m, i, x,
    q, which makes the pattern literal and leaves the replacement's references), replaced, an empty match just after a
    match left alone; None for None, or for flags or a pattern SPARQL refuses. A pattern python_pattern refuses raises
    ValueError."""
    if text is None or pattern is None or replacement is None:
        return None
    flags = flags or ""
    if set(flags) - set("smixq"):
        return None
    try:
        compiled = re.compile(python_pattern(pattern, flags, text),
                              sum(f for name, f in (("s", re.S), ("m", re.M), ("i", re.I), ("x", re.X)) if name in flags))
    except re.error:
        return None
    out, at, start, last = [], 0, 0, None
    while start <= len(text) and (match := compiled.search(text, start)):
        if match.start() == match.end():
            start = match.end() + 1
            if last == match.end():
                continue
        else:
            start = match.end()
        out.append(text[at:match.start()])
        out.append(expanded(replacement, match))
        at = last = match.end()
    out.append(text[at:])
    return "".join(out)


def sparql_sha256(text):
    """SPARQL's SHA256: the UTF-8 bytes' hash in lower-case hexadecimal."""
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def sparql_encode_for_uri(text):
    """SPARQL's ENCODE_FOR_URI: each UTF-8 byte of a character other than A-Z, a-z, 0-9, `-`, `.`, `_` and `~` as %XX,
    upper-case."""
    return None if text is None else quote(text, safe="")


DECIMAL = re.compile(r"([+-]?)([0-9]*)(?:\.([0-9]*))?")
INTEGER_LIMIT = 2 ** 127


def scaled(lexical):
    """An xsd:decimal or xsd:integer lexical form as a count of 10^-18, or None when Oxigraph would hold it ill-typed:
    more than eighteen fractional digits but zeros, or a count outside a signed 128-bit integer's range."""
    match = DECIMAL.fullmatch(lexical or "")
    if not match or not (match.group(2) or match.group(3)):
        return None
    sign, whole, fraction = match.group(1), match.group(2) or "0", (match.group(3) or "").rstrip("0")
    if len(fraction) > 18:
        return None
    value = int(whole) * SCALE + int(fraction.ljust(18, "0") or "0")
    value = -value if sign == "-" else value
    return value if -INTEGER_LIMIT <= value < INTEGER_LIMIT else None


INTEGERS = {XSD + name for name in ("integer", "nonPositiveInteger", "negativeInteger", "long", "int", "short", "byte",
                                    "nonNegativeInteger", "unsignedLong", "unsignedInt", "unsignedShort",
                                    "unsignedByte", "positiveInteger")}
FLOATS = {XSD + "float", XSD + "double"}
CALENDAR = {XSD + "dateTime", XSD + "date", XSD + "gYear", XSD + "gYearMonth"}
COMPARED_ELSEWHERE = {XSD + name for name in ("time", "duration", "dayTimeDuration", "yearMonthDuration", "gMonth",
                                              "gDay", "gMonthDay")}
FLOAT = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?|[+-]?INF|NaN")
INTEGER = re.compile(r"[+-]?[0-9]+")


def number(term):
    """A numeric literal's value, exact for an integer or a decimal and a float otherwise, or None when ill-typed."""
    if term.datatype in FLOATS:
        return float(term.value.replace("INF", "inf")) if FLOAT.fullmatch(term.value) else None
    if term.datatype in INTEGERS:
        if not INTEGER.fullmatch(term.value) or not -2 ** 63 <= int(term.value) < 2 ** 63:
            return None
        return int(term.value) * SCALE
    return scaled(term.value)


BOOLEAN = {"false": 0, "0": 0, "true": 1, "1": 1}


def order(a, b):
    return (a > b) - (a < b)


def sparql_compare(left, right):
    """-1, 0 or 1 as SPARQL 1.1's <, = and > order two terms given as N-Triples, so IF(?a < ?b, -1, IF(?a = ?b, 0,
    IF(?a > ?b, 1, error))); None where that raises an error. Two numbers compare by value, a NaN with nothing, and two
    booleans false before true; any other two terms that are one term are equal, whatever their kind; else None for a
    term that is no literal, two literals of datatypes < does not compare, an ill-typed one, and a value with no zone
    within fourteen hours of one with a zone. A datatype SPARQL compares but this does not, such as xsd:time or a
    duration, raises."""
    a, b = parsed(left), parsed(right)
    if a is None or b is None:
        return None
    numeric = INTEGERS | FLOATS | {XSD + "decimal"}
    x, y = (number(a), number(b)) if a.datatype in numeric and b.datatype in numeric else (None, None)
    if a == b and (x is None or y is None):
        return 0
    if a.kind != LITERAL or b.kind != LITERAL:
        return None
    if a.datatype in numeric and b.datatype in numeric:
        if x is None or y is None:
            return None
        if a.datatype in FLOATS or b.datatype in FLOATS:
            x = x if a.datatype in FLOATS else x / SCALE
            y = y if b.datatype in FLOATS else y / SCALE
            if x != x or y != y:
                return None
        return order(x, y)
    if {a.datatype, b.datatype} & COMPARED_ELSEWHERE:
        raise ValueError(f"sparql_compare does not compare {a.datatype} and {b.datatype}")
    if a.datatype != b.datatype:
        return None
    if a.datatype == XSD + "string":
        return order(a.value, b.value)
    if a.datatype == XSD + "boolean":
        x, y = BOOLEAN.get(a.value), BOOLEAN.get(b.value)
        return None if x is None or y is None else order(x, y)
    if a.datatype == LANG_STRING:
        return order(a.value, b.value) if a.lang.lower() == b.lang.lower() else None
    if a.datatype in CALENDAR:
        x, y = moment(a.datatype, a.value), moment(b.datatype, b.value)
        if x is None or y is None:
            return None
        if x.zoned == y.zoned:
            return order(x.at, y.at)
        return order(x.at, y.at) if abs(x.at - y.at) > FOURTEEN_HOURS else None
    return None


FUNCTIONS = {"sparql_replace": sparql_replace, "sparql_sha256": sparql_sha256,
             "sparql_encode_for_uri": sparql_encode_for_uri, "sparql_compare": sparql_compare}


# The order of rows

def read_as_text(condition):
    """How an ORDER BY condition reads its variable where it orders by its STR: the position its text is taken from,
    the length taken, None for the rest, and whether an unbound value reads as "", as in
    DESC(COALESCE(SUBSTR(STR(?a), 1, 10), "")); None where it orders the term itself."""
    if not re.search(r"\bSTR\s*\(\s*\?\w+\s*\)", condition):
        return None
    cut = re.search(r"SUBSTR\s*\(\s*STR\s*\(\s*\?\w+\s*\)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)", condition)
    return (int(cut[1]) if cut else 1, int(cut[2]) if cut and cut[2] else None,
            re.search(r',\s*""\s*\)', condition) is not None)


def as_text(term, read):
    """The value a condition reading its variable as text, as read_as_text gives it, orders the term by."""
    start, length, unbound_empty = read
    text = None if term is None or term.kind == BLANK else term.value
    if text is not None:
        text = text[start - 1:None if length is None else start - 1 + length]
    return "" if text is None and unbound_empty else text


FIRST_BOUND = re.compile(r"COALESCE\s*\(\s*(\?\w+(?:\s*,\s*\?\w+)*)\s*\)")


def final_order(text, names):
    """The keys the query's rows are ordered by, after its last brace, one for each condition of its ORDER BY, each the
    columns whose first bound value it orders by and how it reads that, as read_as_text gives: a condition is a
    projected variable, or a COALESCE of projected variables, alone or in an expression of it and of no other variable,
    such as DESC(COALESCE(STR(?a), "")) or COALESCE(SUBSTR(STR(COALESCE(?a, ?b)), 1, 10), ""). None when the query has
    no ORDER BY there; a condition that is not one of these is a ValueError naming it, never a key left out."""
    tail = text[text.rfind("}"):]
    clause = re.search(r"ORDER\s+BY\s", tail)
    if not clause:
        return None
    rest, keys = tail[clause.end():].strip(), []
    while rest:
        variable = re.match(r"\?(\w+)", rest)
        if variable:
            condition = variable.group(0)
        else:
            call = re.match(r"\w+\s*\(", rest)
            if not call:
                raise ValueError(f"no key can be read from the ORDER BY condition {rest.split()[0]}")
            depth, at = 0, call.end() - 1
            for at in range(call.end() - 1, len(rest)):
                depth += {"(": 1, ")": -1}.get(rest[at], 0)
                if depth == 0:
                    break
            condition = rest[:at + 1]
        coalesced = FIRST_BOUND.search(condition)
        shape = FIRST_BOUND.sub("?_", condition, count=1) if coalesced else condition
        others = set(re.findall(r"\?(\w+)", re.sub(r'"[^"]*"', "", shape)))
        found = re.findall(r"\w+", coalesced[1]) if coalesced else sorted(others)
        if others != ({"_"} if coalesced else set(found)) or len(others) != 1 or not set(found) <= set(names):
            raise ValueError(f"no key can be read from the ORDER BY condition {condition}")
        keys.append((tuple(names.index(each) for each in found), read_as_text(shape)))
        rest = rest[len(condition):].strip()
    return keys


def tied(left, right):
    """Whether an ORDER BY may put two terms either way round: one term, two blank nodes, or two literals SPARQL's `<`
    does not order, such as a value with no zone and one with a zone within fourteen hours of it, whose order is the
    engine's own."""
    if left == right:
        return True
    if left is None or right is None or left.kind != right.kind or left.kind == IRI:
        return False
    if left.kind == BLANK:
        return True
    try:
        return sparql_compare(str(left), str(right)) in (None, 0)
    except ValueError:
        return True


def ordered(one, other, keys):
    """Whether an ORDER BY of the keys puts the two rows one way round: the first key whose value differs, a text a
    condition reads or else the term, holds two texts, or two terms SPARQL's `<` orders."""
    for columns, read in keys:
        left, right = (next((row[column] for column in columns if row[column] is not None), None) for row in (one, other))
        if read is not None:
            if as_text(left, read) != as_text(right, read):
                return True
        elif left != right:
            return not tied(left, right)
    return False


def runs(found, keys):
    """The lengths of the rows' runs, in their order: a run ends where the ORDER BY's keys put a row and the next one
    way round."""
    lengths = [1] if found else []
    for one, other in zip(found, found[1:]):
        if ordered(one, other, keys):
            lengths.append(1)
        else:
            lengths[-1] += 1
    return lengths


def shown(names, found):
    return " ".join(f"?{name}={value}" for name, value in zip(names, found) if value is not None)


def written(found):
    return [str(value) if value is not None else "" for value in found]


def compared(names, wanted, found, keys):
    """Why rows found are not the rows wanted, as lines, or none when they are: as multisets, and, given the key columns
    of an ORDER BY, as the same runs of rows those keys order, in the same order, the rows of a run being a multiset;
    so where SPARQL leaves two rows' order to the engine, as it does for rows the keys tie, either order passes."""
    lacking, extra = Counter(wanted) - Counter(found), Counter(found) - Counter(wanted)
    lines = [*(f"missing: {shown(names, r)}" for r in sorted(lacking.elements(), key=written)),
             *(f"unexpected: {shown(names, r)}" for r in sorted(extra.elements(), key=written))]
    if lines or keys is None:
        return lines
    at = 0
    for length in runs(wanted, keys):
        run = wanted[at:at + length]
        if Counter(run) != Counter(found[at:at + length]):
            wrong = next((i for i in range(at, at + length) if found[i] not in run), at)
            return [f"the same rows in another order, from row {wrong + 1}: expected "
                    f"{' or '.join(shown(names, r) for r in run)}, found {shown(names, found[wrong])}"]
        at += length
    return lines


# The loader

MINIMUM_VERSION = tuple(map(int, re.search(r"SQLite (\d+)\.(\d+)\.(\d+)", SCHEMA.read_text(encoding="utf-8")).groups()))


COMPILED = 1024


def connected():
    """An empty pod in memory, the schema made and the functions registered, keeping enough statements compiled
    that a refill of every screen compiles none again."""
    connection = sqlite3.connect(":memory:", cached_statements=COMPILED)
    connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    for name, function in FUNCTIONS.items():
        connection.create_function(name, -1, function, deterministic=True)
    return connection


RECORD = "https://ns.cascadeprotocol.org/cascade#Record"
ENTRY_MEMBER = "https://ns.cascadeprotocol.org/cascade#entryMember"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def loaded(store, fingerprint):
    """The pod of an Oxigraph store's named graphs, every record and entry in scope, as a whole run fills it, and the
    ledger's one row naming what it was made from."""
    connection = connected()
    ids, terms = {}, []

    def term_id(node):
        found = ids.get(node)
        if found is None:
            term = from_oxigraph(node)
            found = ids[node] = len(ids) + 1
            terms.append((found, str(term), term.kind, None if term.kind == BLANK else term.value, term.datatype,
                          term.lang, instant_key(term), day_key(term)))
        return found

    quads = [(term_id(q.subject), term_id(q.predicate), term_id(q.object), term_id(q.graph_name))
             for q in store.quads_for_pattern(None, None, None, None)
             if not isinstance(q.graph_name, pyoxigraph.DefaultGraph)]
    connection.executemany("INSERT INTO term (id, nt, kind, lex, datatype, lang, instant, day) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", terms)
    connection.executemany("INSERT INTO quad (s, p, o, g) VALUES (?, ?, ?, ?)", quads)
    connection.execute("INSERT INTO ledger (built, fingerprint) VALUES ('pod', ?)", (fingerprint,))
    connection.execute("INSERT INTO scope (term) SELECT s FROM quad WHERE p = (SELECT id FROM term WHERE nt = ?) "
                       "AND o = (SELECT id FROM term WHERE nt = ?) "
                       "UNION SELECT s FROM quad WHERE p = (SELECT id FROM term WHERE nt = ?)",
                       (f"<{RDF_TYPE}>", f"<{RECORD}>", f"<{ENTRY_MEMBER}>"))
    connection.commit()
    return connection


PART = re.compile(r"^-- part: (\w+)[ \t]*$", re.MULTILINE)
PARTS = ("tables", "fill", "finish", "triples")
LABELS_PARTS = ("fill", "triples")
QUESTION_PARTS = (("prepare", "answer"), ("prepare", "answer", "cleanup"))


def parts(text):
    """A `.sql` by its parts, each the text after its `-- part: NAME` line up to the next, as
    queries/statements.sql orders them; empty for a `.sql` in no parts."""
    found = PART.split(text)[1:]
    named = dict(zip(found[::2], found[1::2]))
    if named and list(named) not in (list(PARTS), list(LABELS_PARTS)) and tuple(named) not in QUESTION_PARTS:
        raise ValueError(f"a .sql has the parts {list(named)}, not {list(PARTS)}, {list(LABELS_PARTS)}, "
                         f"{list(QUESTION_PARTS[0])} or {list(QUESTION_PARTS[1])}")
    return named


@cache
def statements(script):
    """A script's statements, in order, each as SQLite reads one."""
    found, pending = [], ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            found.append(pending)
            pending = ""
    if pending.strip() and not all(line.lstrip().startswith("--") or not line.strip() for line in pending.splitlines()):
        raise ValueError(f"a script ends in an unfinished statement: {pending[:200]!r}")
    return found


def statement(text):
    """What a `.sql` gives its `.rq`'s rows by: a view's triples part, a question's answer part, or the whole text of any
    other."""
    found = parts(text)
    return found.get("triples", found.get("answer", text))


def prepared(text):
    """The statements a question's `.sql` runs before its answer, in order: those of its prepare part, none for a `.sql`
    with none."""
    return statements(parts(text).get("prepare", ""))


def screened(connection, views):
    """The connection with the screen of each view's `.sql` text made and filled for the entries in scope, every
    view's fill before any view's finish."""
    for found in views:
        connection.executescript(parts(found)["tables"])
    texts = [parts(text) for text in views]
    for name in PARTS[1:3]:
        for found in texts:
            for each in statements(found[name]):
                connection.execute(each)
    connection.commit()
    return connection
