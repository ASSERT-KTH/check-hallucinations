"""Candidate choice: a title shared by reviews, reprints and later papers is the cited work when one
candidate (Semantic Scholar, then OpenAlex) has the entry's authors and year."""

import pytest

from check_hallucinations import main as m

# Semantic Scholar records, abridged from the answers of October 2026.
SS = {
    "swinburne": ("OBJECTIVE KNOWLEDGE: AN EVOLUTIONARY APPROACH", 1973, ["R. Swinburne"]),
    "martin": ("Objective Knowledge: An Evolutionary Approach.", 1975, ["J. A. Martin", "K. Popper"]),
    "popper": ("Objective Knowledge: An Evolutionary Approach", 1972, ["K. Popper"]),
    "martinez": ("Experimentation and Scientific Realism: A Return to Francis Bacon", 2021,
                 ["María Laura Martínez Rodríguez"]),
    "minogue": ("The Concept of Mind", 2017, ["K. Minogue"]),
    "weldon": ("The Concept of Mind", 1950, ["T. Weldon"]),
}
# OpenAlex works, abridged.
HACKING = {"title": "Experimentation and Scientific Realism", "year": 1982, "authors": ["Ian Hacking"],
           "url": "https://openalex.org/W1"}
RYLE = {"title": "The Concept of Mind", "year": 2009, "authors": ["Gilbert Ryle"], "url": "https://openalex.org/W2"}


@pytest.fixture
def lookup(monkeypatch):
    """Semantic Scholar yields the given records, OpenAlex the given works."""
    state = {"ss": [], "openalex": []}

    def candidates(title, entry=None):
        for pid in state["ss"]:
            yield {"paperId": pid, "title": SS[pid][0]}

    def info(pid):
        title, year, names = SS[pid]
        return {"paperId": pid, "title": title, "year": year, "authors": [{"name": n} for n in names]}
    monkeypatch.setattr(m, "_candidates", candidates)
    monkeypatch.setattr(m, "_get_paper_info", info)
    monkeypatch.setattr(m, "_url_for_paper", lambda p: "ss:" + p["paperId"])
    monkeypatch.setattr(m, "_openalex_works", lambda t: state["openalex"])
    return state


def entry(kind, key, author, title, year):
    return {"ID": key, "LINE": 1, "ENTRYTYPE": kind, "author": author, "title": title, "year": year}


def rules(r):
    return [f.rule for f in r.findings]


POPPER = ("Popper, Karl R.", "Objective Knowledge: An Evolutionary Approach")


def test_later_candidate_with_authors_and_year(lookup):  # known-positive: was year-mismatch 1975
    lookup["ss"] = ["swinburne", "martin", "popper"]
    r = m.check_entry(entry("article", "popper1972objective", *POPPER, "1972"))
    assert (r.url, r.findings) == ("ss:popper", [])


def test_no_candidate_with_the_year(lookup):  # known-negative: an invented year is still reported
    lookup["ss"] = ["swinburne", "martin", "popper"]
    r = m.check_entry(entry("article", "k", *POPPER, "1990"))
    assert rules(r) == ["year-mismatch"]


HACKING_ENTRY = ("Experimentation and Scientific Realism", "1982")


def test_openalex_has_the_cited_paper(lookup):  # known-positive: Semantic Scholar has only a 2021 paper
    lookup["ss"], lookup["openalex"] = ["martinez"], [HACKING]
    r = m.check_entry(entry("article", "hacking1982experimentation", "Hacking, Ian", *HACKING_ENTRY))
    assert (r.url, r.findings) == ("https://openalex.org/W1", [])


def test_wrong_author_still_reported(lookup):  # known-negative: no candidate has the cited author
    lookup["ss"], lookup["openalex"] = ["martinez"], [HACKING]
    r = m.check_entry(entry("article", "k", "Smith, John", *HACKING_ENTRY))
    assert rules(r) == ["authors-mismatch", "year-mismatch"]
    assert "Martínez" in r.findings[0].message  # Semantic Scholar's answer stands: OpenAlex is no better


def test_openalex_without_title_match_changes_nothing(lookup):
    lookup["ss"], lookup["openalex"] = ["martinez"], [{**HACKING, "title": "Representing and Intervening"}]
    r = m.check_entry(entry("article", "k", "Hacking, Ian", *HACKING_ENTRY))
    assert rules(r) == ["authors-mismatch", "year-mismatch"]


RYLE_BOOK = ("Ryle, Gilbert", "The Concept of Mind")


def test_book_reprinted_later(lookup):  # known-positive: reviews in 1950 and 2017, a 2009 edition
    lookup["ss"], lookup["openalex"] = ["minogue", "weldon"], [RYLE]
    r = m.check_entry(entry("book", "ryle1949concept", *RYLE_BOOK, "1949"))
    assert (r.url, r.findings) == ("https://openalex.org/W2", [])


def test_book_dated_after_every_edition(lookup):  # boundary: a later edition explains an earlier year only
    lookup["ss"], lookup["openalex"] = ["minogue"], [RYLE]
    r = m.check_entry(entry("book", "k", *RYLE_BOOK, "2015"))
    assert rules(r) == ["year-mismatch"]


def test_article_is_not_a_reprint(lookup):  # known-negative: the edition rule is for books
    lookup["ss"], lookup["openalex"] = ["minogue"], [RYLE]
    r = m.check_entry(entry("article", "k", *RYLE_BOOK, "1949"))
    assert rules(r) == ["year-mismatch"]


def test_book_with_invented_author(lookup):  # known-negative
    lookup["ss"], lookup["openalex"] = ["minogue", "weldon"], [RYLE]
    r = m.check_entry(entry("book", "k", "Doe, Jane", "The Concept of Mind", "1949"))
    assert rules(r) == ["authors-mismatch"]
