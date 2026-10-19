#!/usr/bin/env python3
"""
Process a BibTeX file and check each reference for hallucinations via Semantic Scholar.
"""

import argparse
import hashlib
import itertools
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field

import bibtexparser
import keyring
import requests

from . import _metadata

SEMANTICSCHOLAR_DELAY = 1.0
CACHE_DIR = os.path.expanduser("~/.cache/check-hallucinations")

# Quotes are typographical decoration for title matching.  Treating them as
# word boundaries makes BibTeX's TeX-style ``...'' quotes compare equal to
# straight or curly quotes, including API metadata missing a space after one.
_TITLE_QUOTE_TRANSLATION = str.maketrans(
    {quote: " " for quote in "`'\"\u2018\u2019\u201c\u201d"}
)


def _api_key():
    key = os.environ.get("SEMANTICSCHOLAR_API_KEY") or keyring.get_password("check-hallucinations", "ss_api_key") or ""
    return {"x-api-key": key} if key else {}


def _strip_diacritics(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _normalize_title(title):
    normalized = _strip_diacritics(
        title.lower()
        .strip()
        .translate(_TITLE_QUOTE_TRANSLATION)
        .rstrip(".")
        .replace("--", "-")
        .replace("\\$", "$")
        .replace("\\%", "%")
        .replace("\\&", "&")
        .replace("\\#", "#")
        .replace(": ", ". ")
        .replace(",", " ")
        .replace("{", "")
        .replace("}", "")
        .replace(" ", " ")
        .replace("‐", "")
        .replace("‑", "")
        .replace("·", "-")
        .replace(" - ", "-")
        .replace("-", " ")
        .replace(" ...", "...")
    )
    # Sentence punctuation is decoration too: "Remediation : A Case", "Bot?: Insights".
    return " ".join(re.sub(r"[.:;?!]", " ", normalized).split())


def _cache_path(subdir, key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    path = os.path.join(CACHE_DIR, subdir)
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, digest + ".json")


def _get_doi_target(doi):
    url = f"https://doi.org/{doi}"
    response = requests.get(url, allow_redirects=True)
    response.raise_for_status()
    return response.url


class DoiNotFound(Exception):
    pass


def _doi_metadata(doi):
    """The CSL-JSON record of a DOI, from doi.org (Crossref and DataCite alike, so arXiv DOIs too).

    DoiNotFound when doi.org does not know it, Unchecked when it cannot be reached.
    """
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.IGNORECASE)
    fname = _cache_path("doi_csl", doi.lower())
    if os.path.exists(fname):
        with open(fname) as f:
            return json.load(f)
    try:
        resp = requests.get(f"https://doi.org/{doi}", timeout=30, allow_redirects=True,
                            headers={"Accept": "application/vnd.citationstyles.csl+json",
                                     "User-Agent": "check-hallucinations/1.0"})
    except requests.RequestException as e:
        raise Unchecked(f"doi.org unreachable: {e}") from e
    if resp.status_code == 404:
        raise DoiNotFound(f"doi {doi} does not exist")
    if resp.status_code != 200:
        raise Unchecked(f"doi.org answered HTTP {resp.status_code} for {doi}")
    try:
        data = resp.json()
    except ValueError as e:
        raise Unchecked(f"doi.org gave no metadata for {doi}") from e
    with open(fname, "w") as f:
        json.dump(data, f)
    return data


_ARXIV_ID_RE = re.compile(r'(?:arXiv[:\s]+|arxiv\.org/(?:abs|pdf|html)/)(\d{4}\.\d{4,5}(?:v\d+)?)', re.IGNORECASE)


def _detect_arxiv_id(entry):
    """Return the arXiv ID string if the entry looks like an arXiv paper, else None."""
    for field in ('howpublished', 'journal', 'eprint', 'url', 'note'):
        val = entry.get(field, '')
        if val:
            m = _ARXIV_ID_RE.search(val)
            if m:
                return m.group(1)
    return None


def check_arxiv(arxiv_id, bib_title):
    fname = _cache_path("arxiv", arxiv_id)
    if os.path.exists(fname):
        with open(fname) as f:
            api_title = json.load(f)["title"]
    else:
        url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
        resp = requests.get(url, timeout=15, headers={"User-Agent": "check-hallucinations/1.0"})
        resp.raise_for_status()
        # arxiv API wraps entries in <entry><title>…</title>; first <title> is feed title
        titles = re.findall(r'<title>(.*?)</title>', resp.text, re.DOTALL)
        if len(titles) < 2:
            raise MiscEntryError(f"arXiv ID not found: {arxiv_id}")
        api_title = titles[1].strip().replace('\n', ' ')
        with open(fname, "w") as f:
            json.dump({"title": api_title}, f)

    if not _title_matches(api_title, bib_title):
        raise MiscEntryError(
            f"arXiv title mismatch: bib={bib_title!r} arxiv={api_title!r}"
        )


class MiscEntryError(Exception):
    pass


def _report_bug():
    print("  If the paper truly exists in https://www.semanticscholar.org/ report a bug at "
          "https://github.com/ASSERT-KTH/check-hallucinations/ else report a bug at feedback@semanticscholar.org")


def _extract_url(howpublished):
    m = re.search(r'\\url\{([^}]+)\}', howpublished)
    if m:
        return m.group(1)
    m = re.search(r'https?://\S+', howpublished)
    if m:
        return m.group(0)
    return None


def _fetch_page_title(url):
    fname = _cache_path("page_title", url)
    if os.path.exists(fname):
        with open(fname) as f:
            return json.load(f)["title"]
    resp = requests.get(url, timeout=10, allow_redirects=True,
                        headers={"User-Agent": "check-hallucinations/1.0"})
    resp.raise_for_status()
    m = re.search(r'<title[^>]*>([^<]+)</title>', resp.text, re.IGNORECASE)
    title = m.group(1).strip() if m else ""
    with open(fname, "w") as f:
        json.dump({"title": title}, f)
    return title


def check_misc_url(url, bib_title):
    page_title = _fetch_page_title(url)
    if not page_title:
        raise MiscEntryError(f"No <title> found at {url}")
    # When the bib title has a colon, the part after it is the real title
    search_title = bib_title.split(":", 1)[1].strip() if ":" in bib_title else bib_title
    norm_bib = _normalize_title(search_title)
    norm_page = _normalize_title(page_title)
    if norm_bib not in norm_page and norm_page not in norm_bib:
        raise MiscEntryError(
            f"Title does not match page: {bib_title!r} not found in {page_title!r}"
        )


class SemanticScholarNotFound(Exception):
    pass


class Unchecked(Exception):
    """A lookup failed (network, rate limit, server error): the entry is neither confirmed nor refuted."""


SS_RETRY_WAITS = [5, 15, 30]


def _ss_get(url):
    """GET a Semantic Scholar URL, retrying on 429; Unchecked when it never answers."""
    for wait in [*SS_RETRY_WAITS, None]:
        try:
            resp = requests.get(url, headers=_api_key(), timeout=30)
        except requests.RequestException as e:
            raise Unchecked(f"Semantic Scholar unreachable: {e}") from e
        if resp.status_code == 429 and wait is not None:
            time.sleep(wait)
            continue
        time.sleep(SEMANTICSCHOLAR_DELAY)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise Unchecked(f"Semantic Scholar answered HTTP {resp.status_code}")
        return resp
    raise AssertionError("unreachable")


def _ss_match(title):
    """Call the /match endpoint; returns a single {paperId, title} or None."""
    fname = _cache_path("title_to_id", _normalize_title(title))
    if os.path.exists(fname):
        try:
            with open(fname) as f:
                return json.load(f)
        except Exception:
            os.remove(fname)

    query = title.replace("’", "").replace("’", "")
    url = "https://api.semanticscholar.org/graph/v1/paper/search/match?query=" + query
    resp = _ss_get(url)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if "data" not in data:
        return None
    result = data["data"][0]
    with open(fname, "w") as f:
        json.dump(result, f)
    return result


def _ss_search(title):
    """Call the /search endpoint; returns a list of up to 5 {paperId, title}."""
    fname = _cache_path("search_results", _normalize_title(title))
    if os.path.exists(fname):
        with open(fname) as f:
            return json.load(f)

    query = title.replace("’", "").replace("’", "")
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        "?query=" + query + "&fields=title,paperId&limit=5"
    )
    resp = _ss_get(url)
    if resp.status_code != 200:
        return []
    results = resp.json().get("data", [])
    with open(fname, "w") as f:
        json.dump(results, f)
    return results


def _first_author_last_name(author_field):
    if not author_field:
        return None
    first = author_field.split(" and ")[0].strip()
    # "Last, First" BibTeX format
    if "," in first:
        return first.split(",")[0].strip()
    # "First Last" format
    parts = first.split()
    return parts[-1] if parts else None


def _title_matches(ss_title, bib_title):
    norm_ss = _normalize_title(ss_title)
    norm_bib = _normalize_title(bib_title)

    # Exact match (handles different separators, diacritics, braces, etc.)
    if norm_ss == norm_bib:
        return True

    # Check if the SS main title (part before colon) matches the full bib title.
    # Handles case where bib title omits the subtitle.
    ss_main = _normalize_title(ss_title.split(":")[0])
    if ss_main == norm_bib:
        return True

    # Check if the bib main title (part before colon) matches the full SS title.
    # Handles case where SS title omits the subtitle.
    bib_main = _normalize_title(bib_title.split(":")[0])
    if bib_main == norm_ss:
        return True

    # Prefix match — handles trailing artefacts appended by some sources (e.g. ☆).
    if norm_ss.startswith(norm_bib) or norm_bib.startswith(norm_ss):
        return True

    return False


def _get_paper_info(paper_id):
    """The Semantic Scholar record of a paper; only a real record is cached.

    Earlier versions cached any answer, including "Too Many Requests": such a cached
    error (no `paperId`) is fetched again.
    """
    fname = _cache_path("paper_info", paper_id)
    if os.path.exists(fname):
        with open(fname) as f:
            data = json.load(f)
        if "paperId" in data:
            return data
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/"
        + paper_id
        + "?fields=title,authors,year,venue,externalIds,fieldsOfStudy,tldr"
    )
    resp = _ss_get(url)
    if resp.status_code != 200:
        raise Unchecked(f"Semantic Scholar has no record {paper_id} (HTTP {resp.status_code})")
    data = resp.json()
    with open(fname, "w") as f:
        json.dump(data, f)
    return data


def _url_for_paper(result):
    try:
        data = _get_paper_info(result["paperId"])
    except Unchecked:
        return "https://www.semanticscholar.org/paper/" + result["paperId"]
    if "externalIds" in data:
        if "DOI" in data["externalIds"]:
            try:
                return _get_doi_target(data["externalIds"]["DOI"])
            except Exception:
                return "https://doi.org/" + data["externalIds"]["DOI"]
        if "ArXiv" in data["externalIds"]:
            return "https://arxiv.org/abs/" + data["externalIds"]["ArXiv"]
    return "https://www.semanticscholar.org/paper/" + result["paperId"]


def _candidates(title, entry=None):
    """The Semantic Scholar {paperId, title} whose title matches, best first, each once.

    Lazy: a caller that takes the first one makes the same requests as before.
    """
    seen = set()

    def fresh(r):
        if r and "paperId" in r and r["paperId"] not in seen and _title_matches(r["title"], title):
            seen.add(r["paperId"])
            return True
        return False

    # Fast path: /match endpoint
    result = _ss_match(title)
    if fresh(result):
        yield result

    # Retry /match augmented with first author last name (handles short/ambiguous titles)
    author = _first_author_last_name((entry or {}).get("author", ""))
    if author:
        result2 = _ss_match(title + " " + author)
        if fresh(result2):
            yield result2

    # Last resort: /search endpoint, scan first few results
    for candidate in _ss_search(title):
        if fresh(candidate):
            yield candidate

    if not seen:
        if result and "paperId" in result:
            raise SemanticScholarNotFound(
                "Title does not match: " + title + " vs " + result["title"]
            )
        raise SemanticScholarNotFound("not found in SemanticScholar: " + title)


def _find_paper(title, entry=None):
    """The Semantic Scholar {paperId, title} whose title matches; SemanticScholarNotFound otherwise."""
    return next(_candidates(title, entry))


def get_url_from_title(title, entry=None):
    return _url_for_paper(_find_paper(title, entry))


def _parse_library(text):
    """The entries of a BibTeX text, and the 1-based lines of the blocks that do not parse.

    An entry is a dict: field names lowercased, `ENTRYTYPE`, `ID` and `LINE` (1-based).
    @string references are resolved.
    """
    library = bibtexparser.parse_string(text)
    entries = []
    for e in library.entries:
        entry = {f.key.lower(): f.value for f in e.fields}
        entry["ENTRYTYPE"] = e.entry_type.lower()
        entry["ID"] = e.key
        entry["LINE"] = e.start_line + 1
        entries.append(entry)
    return entries, [b.start_line + 1 for b in library.failed_blocks]


def _parse(text):
    """The entries of a BibTeX text (see `_parse_library`); blocks that do not parse are skipped."""
    return _parse_library(text)[0]


@dataclass(frozen=True)
class Finding:
    key: str
    line: int
    rule: str
    message: str


@dataclass
class Result:
    """What `check_entry` established about one entry.

    `url` is set when the entry was confirmed; `error` is the reason it was not (the text the
    library output prints); `findings` lists every problem, metadata ones included.
    """

    kind: str  # "arxiv", "misc" or "entry"
    title: str | None
    url: str | None = None
    error: str | None = None
    findings: list[Finding] = dataclass_field(default_factory=list)

    def add(self, entry, rule, message):
        self.findings.append(Finding(entry["ID"], entry.get("LINE", 0), rule, message))


def _clean_title(title):
    return " ".join(title.replace("{", "").replace("}", "").split()) if title else title


def _check_doi(entry, result):
    doi = entry.get("doi")
    if not doi or not result.title:
        return
    try:
        csl = _doi_metadata(doi)
    except DoiNotFound as e:
        result.add(entry, "doi-not-found", str(e))
        return
    except Unchecked as e:
        result.add(entry, "unchecked", f"doi not checked: {e}")
        return
    doi_title = csl.get("title")
    if isinstance(doi_title, list):
        doi_title = doi_title[0] if doi_title else None
    if doi_title and not _title_matches(doi_title, result.title):
        result.add(entry, "doi-mismatch", f"doi {doi} is {doi_title!r}")


MAX_CANDIDATES = 5


def _metadata_problems(entry, paper):
    """(rule, message) for each way the entry's authors and year are not those of `paper`."""
    info = _get_paper_info(paper["paperId"])
    problems = []
    names = [a.get("name", "") for a in info.get("authors") or []]
    why = _metadata.authors_mismatch(entry.get("author", ""), names)
    if why:
        shown = ", ".join(names[:4]) + (", ..." if len(names) > 4 else "")
        problems.append(("authors-mismatch", f"{why}; the paper is by {shown}"))
    why = _metadata.year_mismatch(entry.get("year"), info.get("year"))
    if why:
        problems.append(("year-mismatch", why))
    return problems


def _best_paper(entry, candidates):
    """The first candidate whose authors are the entry's, and its problems; else the first one's.

    Titles are ambiguous ("Precise Null-pointer Analysis" is the prefix of another paper's
    title), so a candidate whose authors differ is only kept when no other one fits.
    """
    candidates = iter(candidates)
    paper = next(candidates)
    first = (paper, _metadata_problems(entry, paper))
    for _ in range(MAX_CANDIDATES - 1):
        if not any(rule == "authors-mismatch" for rule, _ in first[1]):
            break
        try:
            paper = next(candidates)
            problems = _metadata_problems(entry, paper)
        except (StopIteration, Unchecked):  # no other candidate, or none reachable: keep the first
            break
        if not any(rule == "authors-mismatch" for rule, _ in problems):
            return paper, problems
    return first


def check_entry(entry):
    """Check one parsed entry: its title is found, and its authors, year and DOI are that paper's."""
    title = _clean_title(entry.get("title"))
    if not title:
        result = Result("entry", title, error="no title")
        result.add(entry, "no-title", "the entry has no title to look up")
        return result

    # misc entries without eprint are web references or arXiv preprints
    if entry.get("eprint") is None and entry.get("ENTRYTYPE") == "misc":
        arxiv_id = _detect_arxiv_id(entry)
        if arxiv_id:
            result = Result("arxiv", title)
            try:
                check_arxiv(arxiv_id, title)
                result.url = f"https://arxiv.org/abs/{arxiv_id}"
            except MiscEntryError as e:
                result.error = str(e)
                rule = "arxiv-not-found" if "not found" in str(e) else "arxiv-mismatch"
                result.add(entry, rule, str(e))
            except Exception as e:
                result.error = str(e)
                result.add(entry, "unchecked", f"arXiv not reached: {e}")
            _check_doi(entry, result)
            return result

        result = Result("misc", title)
        url = _extract_url(entry.get("howpublished", ""))
        if not url:
            result.add(entry, "no-url", "web reference without a URL in howpublished, cannot be checked")
            return result
        try:
            check_misc_url(url, title)
            result.url = url
        except MiscEntryError as e:
            result.error = str(e)
            result.add(entry, "web-mismatch", str(e))
        except requests.HTTPError as e:
            result.error = str(e)
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                result.add(entry, "web-not-found", f"{url} answers HTTP {status}")
            else:
                result.add(entry, "unchecked", f"{url} not checked: {e}")
        except Exception as e:
            result.error = str(e)
            result.add(entry, "unchecked", f"{url} not checked: {e}")
        _check_doi(entry, result)
        return result

    result = Result("entry", title)
    try:
        candidates = _candidates(title, entry)
        paper = next(candidates)
    except SemanticScholarNotFound as e:
        result.error = str(e)
        rule = "title-mismatch" if str(e).startswith("Title does not match") else "not-found"
        result.add(entry, rule, str(e))
        _check_doi(entry, result)
        return result
    except Exception as e:
        result.error = str(e)
        result.add(entry, "unchecked", f"Semantic Scholar not checked: {e}")
        return result
    try:
        paper, problems = _best_paper(entry, itertools.chain([paper], candidates))
    except Unchecked as e:
        problems = [("unchecked", f"authors and year not checked: {e}")]
    result.url = _url_for_paper(paper)
    for rule, message in problems:
        result.add(entry, rule, message)
    _check_doi(entry, result)
    return result


def process_bibtex_file(filepath):
    try:
        with open(filepath) as bibtex_file:
            entries = _parse(bibtex_file.read())
    except Exception as e:
        print(f"Error reading BibTeX file: {e}")
        return

    print(f"Processing {len(entries)} entries from {filepath}")

    labels = {"arxiv": "ArXiv", "misc": "Misc", "entry": "Entry"}
    for i, entry in enumerate(entries, 1):
        result = check_entry(entry)
        label = labels[result.kind]
        if result.kind == "misc" and result.url is None and result.error is None:
            print(f"\033[93m\nInternet resource with no URL {i}/{len(entries)}: {result.title}\033[0m")
        elif result.url is None:
            print(result.error)
            print(f"\033[91m\nHallucinated {label} {i}/{len(entries)}: {result.title}\033[0m")
            _report_bug()
        else:
            print(f"\n{label} {i}/{len(entries)}: {result.title}")
            print(f"URL: {result.url}")
            for f in result.findings:
                print(f"\033[93m{f.rule}: {f.message}\033[0m")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check BibTeX references for hallucinations: each title is looked up (Semantic "
                    "Scholar, arXiv, the web page), and the authors, year and DOI must be that paper's. "
                    "Silent when every entry is confirmed; one `file:line: rule: key: message` per finding.",
        epilog="exit status: 0 every entry confirmed, 1 findings, 2 the file cannot be read. "
               "Rules: not-found, title-mismatch, authors-mismatch, year-mismatch, doi-not-found, "
               "doi-mismatch, arxiv-not-found, arxiv-mismatch, web-mismatch, web-not-found, no-url, "
               "no-title, unparsed, unchecked (a lookup failed: neither confirmed nor refuted).",
    )
    parser.add_argument("bibtex_file", help="Path to the BibTeX file")
    parser.add_argument("--json", action="store_true", help="print the findings as a JSON array ([] when clean)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="also print each confirmed entry with its URL")
    args = parser.parse_args(argv)
    try:
        with open(args.bibtex_file) as f:
            entries, failed = _parse_library(f.read())
    except (OSError, UnicodeDecodeError) as e:
        print(f"check-hallucinations: {e}", file=sys.stderr)
        return 2
    findings = [Finding("", line, "unparsed", "BibTeX block that does not parse") for line in failed]
    confirmed = []
    for entry in entries:
        result = check_entry(entry)
        findings += result.findings
        if result.url and not result.findings:
            confirmed.append((entry, result.url))
    findings.sort(key=lambda f: f.line)
    if args.json:
        print(json.dumps([{"file": args.bibtex_file, **asdict(f)} for f in findings], indent=1))
    else:
        if args.verbose:
            for entry, url in confirmed:
                print(f"{args.bibtex_file}:{entry['LINE']}: ok: {entry['ID']}: {url}")
        for f in findings:
            print(f"{args.bibtex_file}:{f.line}: {f.rule}: {f.key}: {f.message}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
