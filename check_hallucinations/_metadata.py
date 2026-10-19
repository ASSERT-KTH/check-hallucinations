"""Compare the authors and the year of a BibTeX entry with those of the paper found for its title.

A hallucinated reference often pairs a real title with invented authors or year: the title is
found, the rest is not that paper's. Comparisons are on last names (an LLM invents names, not
initials) and allow two years of difference (preprint, online-first and issue years differ).
"""

from __future__ import annotations

import re
import unicodedata

# Two years: a journal paper is often online a year before its issue, and Semantic Scholar may
# date a record from a later version (a TSE 2016 paper is 2018 there).
YEAR_SLACK = 2


def _plain(s: str) -> str:
    """Lowercase ASCII letters and spaces: LaTeX accents, braces and diacritics removed."""
    s = re.sub(r"\\[\"'`^~=.uvHcdbtk]\s*", "", s)  # LaTeX accent commands: M{\"u}ller
    s = re.sub(r"\\[A-Za-z]+\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z\s-]", " ", s.lower()).split())


def _last_word(name: str) -> str:
    words = name.replace("-", " ").split()
    return words[-1] if words else ""


def bib_last_names(author_field: str) -> list[str]:
    """Last names of a BibTeX author field (`Last, First` or `First Last`), `others` dropped.

    A corporate author in braces (`{OpenAI}`) is one name.
    """
    names = []
    for raw in re.split(r"\s+and\s+", author_field.strip()):
        raw = raw.strip()
        if not raw or raw.lower() == "others":
            continue
        if raw.startswith("{") and raw.endswith("}") and raw.count("{") == 1:
            names.append(_plain(raw))
            continue
        names.append(_plain(raw.split(",")[0]) if "," in raw else _last_word(_plain(raw)))
    return [n for n in names if n]


def _matches(bib_name: str, found: set[str]) -> bool:
    return _last_word(bib_name) in found or bib_name in found


def authors_mismatch(author_field: str, found_names: list[str]) -> str | None:
    """Why the bib authors are not those found, or None (also when either list is empty).

    A mismatch: the first author is absent, or fewer than half of the bib authors are present.
    """
    bib = bib_last_names(author_field)
    found_plain = [_plain(n) for n in found_names if n]
    if not bib or not found_plain:
        return None
    # Any word of a found name: some records reverse the order ("Monperrus Martin").
    found = {w for n in found_plain for w in n.replace("-", " ").split()} | set(found_plain)
    present = [b for b in bib if _matches(b, found)]
    if not _matches(bib[0], found):
        return f"first author {bib[0]} is not an author"
    if 2 * len(present) < len(bib):
        return f"{len(bib) - len(present)} of {len(bib)} authors are not authors"
    return None


def year_of(field: str | None) -> int | None:
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", field or "")
    return int(m.group(1)) if m else None


def year_mismatch(bib_year: str | None, found_year: int | None) -> str | None:
    """Why the bib year is not the year found, or None (also when either is unknown)."""
    year = year_of(bib_year)
    if year is None or found_year is None or abs(year - found_year) <= YEAR_SLACK:
        return None
    return f"year {year}, but the paper is from {found_year}"
