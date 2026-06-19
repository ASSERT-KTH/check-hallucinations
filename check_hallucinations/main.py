#!/usr/bin/env python3
"""
Process a BibTeX file and check each reference for hallucinations via Semantic Scholar.
"""

import argparse
import hashlib
import json
import os
import re
import time
import unicodedata

import requests
from bibtexparser.bparser import BibTexParser

SEMANTICSCHOLAR_DELAY = 1.0
CACHE_DIR = os.path.expanduser("~/.cache/check-hallucinations")


def _api_key():
    key = os.environ.get("SEMANTICSCHOLAR_API_KEY", "")
    return {"x-api-key": key} if key else {}


def _strip_diacritics(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _normalize_title(title):
    return _strip_diacritics(
        title.lower()
        .strip()
        .rstrip(".")
        .replace("--", "-")
        .replace("\\$", "$")
        .replace("\\%", "%")
        .replace("\\&", "&")
        .replace("\\#", "#")
        .replace(": ", ". ")
        .replace(",", " ")
        .replace("   ", " ")
        .replace("  ", " ")
        .replace("’", "'")
        .replace("{", "")
        .replace("}", "")
        .replace(" ", " ")
        .replace("‐", "")
        .replace("‑", "")
        .replace(" ...", "...")
    )


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


class MiscEntryError(Exception):
    pass


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
    if norm_bib not in norm_page:
        raise MiscEntryError(
            f"Title does not match page: {bib_title!r} not found in {page_title!r}"
        )


class SemanticScholarNotFound(Exception):
    pass


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
    resp = requests.get(url, headers=_api_key())
    time.sleep(SEMANTICSCHOLAR_DELAY)
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
    resp = requests.get(url, headers=_api_key())
    time.sleep(SEMANTICSCHOLAR_DELAY)
    if resp.status_code != 200:
        return []
    results = resp.json().get("data", [])
    with open(fname, "w") as f:
        json.dump(results, f)
    return results


def _title_matches(ss_title, bib_title):
    ss_main = _normalize_title(ss_title.split(":")[0])
    return (
        _normalize_title(ss_title) == _normalize_title(bib_title)
        or ss_main == _normalize_title(bib_title)
    )


def _get_paper_info(paper_id):
    fname = _cache_path("paper_info", paper_id)
    if os.path.exists(fname):
        with open(fname) as f:
            return json.load(f)
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/"
        + paper_id
        + "?fields=title,authors,year,venue,externalIds,fieldsOfStudy,tldr"
    )
    resp = requests.get(url, headers=_api_key())
    data = resp.json()
    with open(fname, "w") as f:
        json.dump(data, f)
    return data


def _url_for_paper(result):
    data = _get_paper_info(result["paperId"])
    if "externalIds" in data:
        if "DOI" in data["externalIds"]:
            try:
                return _get_doi_target(data["externalIds"]["DOI"])
            except Exception:
                return "https://doi.org/" + data["externalIds"]["DOI"]
        if "ArXiv" in data["externalIds"]:
            return "https://arxiv.org/abs/" + data["externalIds"]["ArXiv"]
    return "https://www.semanticscholar.org/paper/" + result["paperId"]


def get_url_from_title(title):
    # Fast path: /match endpoint
    result = _ss_match(title)
    if result and "paperId" in result and _title_matches(result["title"], title):
        return _url_for_paper(result)

    # Fallback: /search endpoint, scan first few results
    for candidate in _ss_search(title):
        if "paperId" in candidate and _title_matches(candidate["title"], title):
            return _url_for_paper(candidate)

    if result and "paperId" in result:
        raise SemanticScholarNotFound(
            "Title does not match: " + title + " vs " + result["title"]
        )
    raise SemanticScholarNotFound("not found in SemanticScholar: " + title)


def process_bibtex_file(filepath):
    try:
        with open(filepath) as bibtex_file:
            parser = BibTexParser(interpolate_strings=False)
            bib_database = parser.parse(bibtex_file.read(), partial=True)
    except Exception as e:
        print(f"Error reading BibTeX file: {e}")
        return

    print(f"Processing {len(bib_database.entries)} entries from {filepath}")

    for i, entry in enumerate(bib_database.entries, 1):
        title = entry.get('title', None)
        if title:
            title = " ".join(title.replace("{", "").replace("}", "").split())

        # misc entries without eprint are web references — check URL and title
        if entry.get("eprint") is None and entry.get('ENTRYTYPE') == 'misc':
            howpublished = entry.get('howpublished', '')
            url = _extract_url(howpublished)
            if not url:
                print(f"\033[91m\nURL with no URL {i}/{len(bib_database.entries)}: {title}\033[0m")
            else:
                try:
                    check_misc_url(url, title)
                    print(f"\nMisc {i}/{len(bib_database.entries)}: {title}")
                    print(f"URL: {url}")
                except Exception as e:
                    print(e)
                    print(f"\033[91m\nHallucinated Misc {i}/{len(bib_database.entries)}: {title}\033[0m")
            continue

        try:
            url = get_url_from_title(title)
            print(f"\nEntry {i}/{len(bib_database.entries)}: {title}")
            print(f"URL: {url}")
        except Exception as e:
            print(e)
            print(f"\033[91m\nHallucinated Entry {i}/{len(bib_database.entries)}: {title}\033[0m")


def main():
    parser = argparse.ArgumentParser(
        description="Check BibTeX references for hallucinations using Semantic Scholar"
    )
    parser.add_argument("bibtex_file", help="Path to the BibTeX file")
    args = parser.parse_args()
    process_bibtex_file(args.bibtex_file)


if __name__ == "__main__":
    main()
