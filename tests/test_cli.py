"""The command line: silent and exit 0 when every entry is confirmed, one line per finding, exit 1."""

import json
from unittest.mock import patch

import pytest

from check_hallucinations import main as m

BIB = """@inproceedings{real,
  author = {Vaswani, Ashish and Shazeer, Noam},
  title = {Attention Is All You Need},
  year = {2017}}

@inproceedings{wrongauthors,
  author = {Smith, John and Doe, Jane},
  title = {Attention Is All You Need},
  year = {2009}}

@article{wrongdoi,
  author = {Vaswani, Ashish},
  title = {Attention Is All You Need},
  year = {2017}, doi = {10.1038/nature14539}}

@article{fake,
  author = {Doe, Jane},
  title = {A Unified Theory of Self-Healing Compilers},
  year = {2024}}
"""

PAPER = {"paperId": "p1", "title": "Attention is All you Need"}
INFO = {"paperId": "p1", "year": 2017, "externalIds": {},
        "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}]}


def find(title, entry=None):
    if "Attention" in title:
        yield PAPER
        return
    raise m.SemanticScholarNotFound("not found in SemanticScholar: " + title)


def doi(d):
    return {"title": "Deep learning"}


@pytest.fixture
def offline():
    with patch.object(m, "_candidates", find), patch.object(m, "_get_paper_info", lambda pid: INFO), \
            patch.object(m, "_doi_metadata", doi), patch.object(m, "_openalex_works", lambda t: []):
        yield


def run(tmp_path, text, *flags):
    bib = tmp_path / "refs.bib"
    bib.write_text(text)
    return m.main([*flags, str(bib)]), str(bib)


def test_clean_is_silent(tmp_path, offline, capsys):  # known-negative
    code, _ = run(tmp_path, BIB.split("@inproceedings{wrongauthors")[0])
    assert code == 0
    assert capsys.readouterr().out == ""


def test_findings(tmp_path, offline, capsys):  # known-positive: 3 hallucinated entries of 4
    code, path = run(tmp_path, BIB)
    assert code == 1
    out = capsys.readouterr().out.splitlines()
    assert [line.split(": ")[0:3] for line in out] == [
        [f"{path}:6", "authors-mismatch", "wrongauthors"],
        [f"{path}:6", "year-mismatch", "wrongauthors"],
        [f"{path}:11", "doi-mismatch", "wrongdoi"],
        [f"{path}:16", "not-found", "fake"],
    ]


def test_json(tmp_path, offline, capsys):
    code, path = run(tmp_path, BIB, "--json")
    found = json.loads(capsys.readouterr().out)
    assert code == 1 and len(found) == 4
    assert found[0] == {"file": path, "key": "wrongauthors", "line": 6, "rule": "authors-mismatch",
                        "message": found[0]["message"]}


def test_verbose_lists_confirmed(tmp_path, offline, capsys):
    with patch.object(m, "_url_for_paper", lambda p: "https://arxiv.org/abs/1706.03762"):
        run(tmp_path, BIB, "-v")
    assert capsys.readouterr().out.splitlines()[0].endswith(": ok: real: https://arxiv.org/abs/1706.03762")


def test_network_failure_is_not_a_hallucination(tmp_path, capsys):  # boundary
    def down(title, entry=None):
        raise m.Unchecked("Semantic Scholar answered HTTP 429")
    with patch.object(m, "_candidates", down):
        code, path = run(tmp_path, BIB.split("@inproceedings{wrongauthors")[0])
    assert code == 1
    assert capsys.readouterr().out.split(": ")[1] == "unchecked"


def test_unparsed_block(tmp_path, offline, capsys):
    code, path = run(tmp_path, "@article{broken, title = {never closed}\n")
    assert code == 1
    assert capsys.readouterr().out == f"{path}:1: unparsed: : BibTeX block that does not parse\n"


def test_ambiguous_title_takes_the_candidate_with_the_authors(tmp_path, capsys):
    # A title that prefixes another paper's title: the first match is by other authors.
    other = {"paperId": "p2", "title": "Precise null pointer analysis through global value numbering"}
    right = {"paperId": "p3", "title": "Precise Null-pointer Analysis"}
    infos = {"p2": {"paperId": "p2", "year": 2017, "authors": [{"name": "Ankush Das"}]},
             "p3": {"paperId": "p3", "year": 2011, "authors": [{"name": "Fausto Spoto"}]}}

    def candidates(title, entry=None):
        yield other
        yield right
    bib = "@article{s, author = {Spoto, Fausto}, title = {Precise Null-pointer Analysis}, year = {2011}}\n"
    with patch.object(m, "_candidates", candidates), patch.object(m, "_get_paper_info", infos.get), \
            patch.object(m, "_url_for_paper", lambda p: p["paperId"]):
        code, _ = run(tmp_path, bib)
    assert (code, capsys.readouterr().out) == (0, "")
    with patch.object(m, "_candidates", lambda t, e=None: iter([other])), \
            patch.object(m, "_get_paper_info", infos.get), patch.object(m, "_url_for_paper", lambda p: ""), \
            patch.object(m, "_openalex_works", lambda t: []):
        code, _ = run(tmp_path, bib)
    assert code == 1 and "authors-mismatch" in capsys.readouterr().out  # only the other paper


def test_unreadable_file(tmp_path, capsys):
    assert m.main([str(tmp_path / "missing.bib")]) == 2
    assert "missing.bib" in capsys.readouterr().err


def test_paper_info_cached_error_is_refetched(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "CACHE_DIR", str(tmp_path))
    cached = m._cache_path("paper_info", "p1")
    with open(cached, "w") as f:
        json.dump({"message": "Too Many Requests"}, f)

    class Resp:
        status_code = 200

        def json(self):
            return INFO

    monkeypatch.setattr(m, "_ss_get", lambda url: Resp())
    assert m._get_paper_info("p1") == INFO
    with open(cached) as f:
        assert json.load(f) == INFO


def test_rate_limit_retried_then_unchecked(monkeypatch):
    class Resp:
        status_code = 429

    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    with pytest.raises(m.Unchecked, match="429"):
        m._ss_get("https://api.semanticscholar.org/x")


def test_no_keyring_backend_means_public_api(monkeypatch):  # CI, servers: no crash
    def no_backend(*args):
        raise m.keyring.errors.NoKeyringError("No recommended backend was available")
    monkeypatch.delenv("SEMANTICSCHOLAR_API_KEY", raising=False)
    monkeypatch.setattr(m.keyring, "get_password", no_backend)
    assert m._api_key() == {}
    monkeypatch.setenv("SEMANTICSCHOLAR_API_KEY", "k")
    assert m._api_key() == {"x-api-key": "k"}
