# check-hallucinations

A command-line tool to detect hallucinated references in BibTeX files before submitting a paper to arXiv.

An entry whose `doi` names a record with its title, authors and year is confirmed by that DOI. Otherwise, it looks up each reference ([Semantic Scholar](https://www.semanticscholar.org/), then [OpenAlex](https://openalex.org/) when Semantic Scholar has no matching title; arXiv; the web page of a `@misc`), and checks that the paper found is the one the entry describes: same title, same authors, same year, and a DOI that resolves to that title.

Titles are decoded from LaTeX to Unicode before the lookup (`Protokolls{\"a}tze` is looked up as `Protokollsätze`), and compared whatever their punctuation and markup: `&`, `#`, `+`, `%`, `?`, `:`, parentheses, quotes, dashes, LaTeX accents and commands (`D\&C`, `C\#`, `Bissyand{\'e}`, `\emph{x}`), and venue names or section numbers (`I.—Knowing How and Knowing that`) that some records prefix to the title. Symbols that change the meaning stay: `C`, `C++` and `C#` are different titles.

## Installation

```bash
pip install check-hallucinations
```

## Usage

```bash
check-hallucinations references.bib            # silent when every entry is confirmed
check-hallucinations --json references.bib     # findings as a JSON array, [] when clean
check-hallucinations -v references.bib         # also list each confirmed entry with its URL
```

One line per finding, `file:line: rule: key: message`:

```
references.bib:5: authors-mismatch: wrongauthors: first author smith is not an author; the paper is by Ashish Vaswani, Noam Shazeer, N. Parmar, J. Uszkoreit, ...
references.bib:5: year-mismatch: wrongauthors: year 2009, but the paper is from 2017
references.bib:9: doi-mismatch: wrongdoi: doi 10.1038/nature14539 is 'Deep learning'
references.bib:13: not-found: fake: not found in SemanticScholar: A Unified Theory of Self-Healing Compilers for Quantum Blockchains
```

Exit status: 0 every entry confirmed, 1 findings, 2 the file cannot be read. This makes it usable as a CI step.

## Rules

- `not-found`, `title-mismatch`: no paper with this title (the closest title is given).
- `authors-mismatch`: the first author is not an author of the paper found, or fewer than half of the authors are. Last names are compared, LaTeX accents and diacritics removed; `and others` is ignored.
- `year-mismatch`: the year differs from the paper's by more than two (preprint, online-first and issue years differ, and Semantic Scholar may date a later version). A `@book` dated before the record found is not a mismatch: the record is a later edition or reprint.

A title is shared by reviews, reprints and later papers ("The Concept of Mind" is also the title of reviews of Ryle's book). Among the first five Semantic Scholar candidates with the title, the first with the entry's authors and year is taken, else the first with its authors; when that one still differs from the entry, OpenAlex is asked, and its work is taken if it fits better. `authors-mismatch` and `year-mismatch` are reported only when no candidate fits.
- `doi-not-found`, `doi-mismatch`: the `doi` field does not exist, or resolves (doi.org, Crossref and DataCite) to another title. A DOI without Crossref or DataCite record (AI Magazine's `10.1609/aimag.*`) exists when the Handle System resolves it, and its title is OpenAlex's.
- `arxiv-not-found`, `arxiv-mismatch`: an arXiv `@misc` whose identifier does not exist or has another title.
- `web-mismatch`, `web-not-found`, `no-url`: a web `@misc` whose page shows another title (in its `<title>`, or each colon-separated part of the entry's title as a phrase of its headings and text), is gone, or has no URL (the `url` field, or `howpublished` as plain text or `\url{}`).
- `no-title`, `unparsed`: an entry without title, a block that is not valid BibTeX.
- `unchecked`: a lookup failed (network, rate limit). The entry is neither confirmed nor refuted; run again.

`misc` entries with an arXiv identifier are checked on arXiv, other `misc` entries on their web page.

## API key

By default the tool uses the public Semantic Scholar API (rate-limited). For higher throughput, set the `SEMANTICSCHOLAR_API_KEY` environment variable (or store it with `keyring set check-hallucinations ss_api_key`):

```bash
export SEMANTICSCHOLAR_API_KEY=your-key-here
check-hallucinations references.bib
```

Answers are cached in `~/.cache/check-hallucinations`.

## Library

`process_bibtex_file(path)` prints the per-entry report of earlier versions (now with author, year and DOI mismatches as extra lines); `check_entry(entry)` returns the findings of one parsed entry.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/mypy check_hallucinations tests scripts
.venv/bin/python scripts/live_check.py [more-real.bib ...]   # network: silent when the lookup is right
uv tool install --editable . --force   # the command on PATH, in its own environment, running this checkout
```

A `pip install --user` of the checkout runs with the system Python's packages, and fails with `module 'bibtexparser' has no attribute 'parse_string'` where that Python has bibtexparser 1.

The live check runs the lookup on `scripts/corpus/real/` (real papers with difficult titles: every entry must be confirmed) and `scripts/corpus/invented/` (every entry must be reported). Add a title that the tool gets wrong to the corpus before fixing it.

## License

MIT
