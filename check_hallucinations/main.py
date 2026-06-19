#!/usr/bin/env python3
"""
Process a BibTeX file and check each reference for hallucinations via Semantic Scholar.
"""

import argparse
import hashlib
import json
import os
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


class SemanticScholarNotFound(Exception):
    pass


def _get_semantic_scholar_id_from_title(title):
    fname = _cache_path("title_to_id", _normalize_title(title))
    if os.path.exists(fname):
        try:
            with open(fname) as f:
                return json.load(f)
        except Exception:
            os.remove(fname)

    query = title.replace(":", "").replace("’", "").replace("'", "")
    url = "https://api.semanticscholar.org/graph/v1/paper/search/match?query=" + query
    resp = requests.get(url, headers=_api_key())
    time.sleep(SEMANTICSCHOLAR_DELAY)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if "data" not in data:
        raise SemanticScholarNotFound("not found in SemanticScholar: " + title)
    result = data["data"][0]
    with open(fname, "w") as f:
        json.dump(result, f)
    return result


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


def get_url_from_title(title):
    result = _get_semantic_scholar_id_from_title(title)
    if not result or "paperId" not in result:
        raise SemanticScholarNotFound("No data found for title: " + title)
    ss_main = _normalize_title(result["title"].split(":")[0])
    if _normalize_title(result["title"]) == _normalize_title(title) or ss_main == _normalize_title(title):
        data = _get_paper_info(result["paperId"])
        if "externalIds" in data:
            if "DOI" in data["externalIds"]:
                try:
                    return _get_doi_target(data["externalIds"]["DOI"])
                except Exception:
                    return "https://doi.org/" + data["externalIds"]["DOI"]
            elif "ArXiv" in data["externalIds"]:
                return "https://arxiv.org/abs/" + data["externalIds"]["ArXiv"]
            return "https://www.semanticscholar.org/paper/" + result["paperId"]
        return "https://www.semanticscholar.org/paper/" + result["paperId"]
    raise SemanticScholarNotFound(
        "Title does not match: "
        + title
        + " vs "
        + result["title"]
    )


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

        # misc entries without eprint are typically non-arxiv web references
        if entry.get("eprint") is None and entry.get('ENTRYTYPE') == 'misc':
            if 'howpublished' not in entry:
                print(f"\033[91m\nURL with no URL {i}/{len(bib_database.entries)}: {title}\033[0m")
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
