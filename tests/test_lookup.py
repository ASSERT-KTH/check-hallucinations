"""Title lookup: queries sent whole, titles compared whatever their punctuation, OpenAlex fallback."""

from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from check_hallucinations import main as m

TRICKY = "Q&A sites: what is C# good for? 100% +1 votes"


def sent_query(monkeypatch, call, title):
    """The `query` parameter Semantic Scholar receives when `call(title)` runs."""
    seen = []

    class Resp:
        status_code = 404

        def json(self):
            return {}

    def get(url, params=None, **kw):
        seen.append(requests.Request("GET", url, params=params).prepare().url)
        return Resp()

    monkeypatch.setattr(m.requests, "get", get)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setattr(m, "_api_key", lambda: {})
    monkeypatch.setattr(m, "CACHE_DIR", "/nonexistent-cache-for-tests")
    monkeypatch.setattr(m, "_cache_path", lambda sub, key: "/nonexistent-cache-for-tests/x")
    call(title)
    return parse_qs(urlsplit(seen[0]).query)["query"][0]


def test_match_query_sent_whole(monkeypatch):  # known-positive: was `Q` until 0.21
    assert sent_query(monkeypatch, m._ss_match, TRICKY) == TRICKY


def test_search_query_sent_whole_without_hyphens(monkeypatch):
    assert sent_query(monkeypatch, m._ss_search, "Divide-and-Conquer: C++ & C#") == "Divide and Conquer: C++ & C#"


@pytest.mark.parametrize("latex,text", [
    (r"D\&C: A Divide-and-Conquer Approach", "D&C: A Divide-and-Conquer Approach"),
    (r"Bissyand\'e and Cruz", "Bissyande and Cruz"),
    (r"Fixing 55 bugs for \$8 each", "Fixing 55 bugs for $8 each"),
    (r"A Replication for C\# Projects", "A Replication for C# Projects"),
    (r"\emph{Big} Code", "Big Code"),
])
def test_query_text(latex, text):
    assert m._query_text(latex) == text


@pytest.mark.parametrize("found,bib", [
    ("How do programmers ask and answer questions on the web?: NIER track",
     "How do programmers ask and answer questions on the web? (NIER track)"),
    ("D&C: A Divide-and-Conquer Approach to IR-based Bug Localization",
     r"D\&C: A Divide-and-Conquer Approach to IR-based Bug Localization"),
    ("Static Analysis Warnings and Automatic Fixing: A Replication for C# Projects",
     r"Static Analysis Warnings and Automatic Fixing: A Replication for C\# Projects"),
    ("We Crunched 1 Billion Java Logged Errors – Here’s What Causes 97% of Them",
     r"We Crunched 1 Billion Java Logged Errors - Here's What Causes 97\% of Them"),
    ("Usenix Association 8th Usenix Symposium on Operating Systems Design and Implementation "
     "Deadlock Immunity: Enabling Systems to Defend Against Deadlocks",
     "Deadlock immunity: Enabling systems to defend against deadlocks"),       # venue prefix
    ("Fixing Recurring Crash Bugs via Analyzing Q&A Sites", r"Fixing Recurring Crash Bugs via Analyzing {Q\&A} Sites"),
])
def test_titles_match(found, bib):
    assert m._title_matches(found, bib)


@pytest.mark.parametrize("found,bib", [
    ("C++ in Depth", "C# in Depth"),                    # known-negative: symbols matter
    ("C Primer", "C++ Primer"),
    ("A survey on contextual multi-armed bandits", "Contextual Multi-Armed Bandits"),
    ("Proceedings of X: Learning to Repair", "Learning to Repair"),   # boundary: suffix too short
    ("History Driven Program Repair", "History driven automated program repair"),
])
def test_titles_differ(found, bib):
    assert not m._title_matches(found, bib)


WORK = {"title": "Automatic Software Repair: a Bibliography", "authors": ["Martin Monperrus"],
        "year": 2018, "url": "https://doi.org/10.1145/3105906"}


def entry(**fields):
    return {"ID": "k", "LINE": 1, "ENTRYTYPE": "article", **fields}


def not_in_ss(title, e=None):
    raise m.SemanticScholarNotFound("not found in SemanticScholar: " + title)
    yield


def test_openalex_fallback_confirms(monkeypatch):
    monkeypatch.setattr(m, "_candidates", not_in_ss)
    monkeypatch.setattr(m, "_openalex_works", lambda t: [WORK])
    r = m.check_entry(entry(title="Automatic Software Repair: a Bibliography", author="Monperrus, Martin",
                            year="2018"))
    assert (r.url, r.findings) == (WORK["url"], [])


def test_openalex_fallback_checks_authors(monkeypatch):  # the fallback is not a free pass
    monkeypatch.setattr(m, "_candidates", not_in_ss)
    monkeypatch.setattr(m, "_openalex_works", lambda t: [WORK])
    r = m.check_entry(entry(title="Automatic Software Repair: a Bibliography", author="Doe, Jane"))
    assert [f.rule for f in r.findings] == ["authors-mismatch"]


def test_openalex_without_match_keeps_not_found(monkeypatch):
    monkeypatch.setattr(m, "_candidates", not_in_ss)
    monkeypatch.setattr(m, "_openalex_works", lambda t: [{**WORK, "title": "Something else entirely"}])
    r = m.check_entry(entry(title="An Invented Title About Quantum Compilers"))
    assert [f.rule for f in r.findings] == ["not-found"] and "nor in OpenAlex" in r.findings[0].message


def test_openalex_unreachable_keeps_not_found(monkeypatch):
    def down(t):
        raise m.Unchecked("OpenAlex unreachable")
    monkeypatch.setattr(m, "_candidates", not_in_ss)
    monkeypatch.setattr(m, "_openalex_works", down)
    assert [f.rule for f in m.check_entry(entry(title="An Invented Title")).findings] == ["not-found"]
