"""DOIs: doi.org metadata (Crossref, DataCite), else the Handle System for existence and OpenAlex for metadata."""

import pytest

from check_hallucinations import main as m

DAVIS = "10.1609/aimag.v14i1.1029"
OPENALEX_DAVIS = {  # https://api.openalex.org/works/doi:10.1609/aimag.v14i1.1029, abridged
    "display_name": "What Is a Knowledge Representation", "publication_year": 1993,
    "authorships": [{"author": {"display_name": "Randall Davis"}}, {"author": {"display_name": "Howard E. Shrobe"}},
                    {"author": {"display_name": "Peter Szolovits B"}}],
}


class Resp:
    def __init__(self, status, data=None):
        self.status_code, self.data = status, data

    def json(self):
        if self.data is None:
            raise ValueError("no JSON")
        return self.data


@pytest.fixture
def web(monkeypatch, tmp_path):
    """`requests.get` answering from a {url prefix: Resp} table; the URLs asked are recorded."""
    monkeypatch.setattr(m, "CACHE_DIR", str(tmp_path))
    table: dict[str, Resp] = {}
    asked: list[str] = []

    def get(url, **kw):
        asked.append(url)
        for prefix, resp in table.items():
            if url.startswith(prefix):
                return resp
        raise AssertionError(f"unexpected request {url}")
    monkeypatch.setattr(m.requests, "get", get)
    return table, asked


def test_no_crossref_record_falls_back_to_openalex(web):  # known-positive: was doi-not-found
    table, _ = web
    table["https://doi.org/api/handles/"] = Resp(200, {"responseCode": 1, "handle": DAVIS})
    table["https://doi.org/"] = Resp(404)
    table["https://api.openalex.org/works/doi:"] = Resp(200, OPENALEX_DAVIS)
    csl = m._doi_metadata(DAVIS)
    assert csl["title"] == "What Is a Knowledge Representation"
    assert m._csl_year(csl) == 1993 and m._csl_names(csl)[0] == "Randall Davis"


def test_doi_that_does_not_resolve(web):  # known-negative: an invented DOI is still not found
    table, _ = web
    table["https://doi.org/api/handles/"] = Resp(404, {"responseCode": 100})
    table["https://doi.org/"] = Resp(404)
    with pytest.raises(m.DoiNotFound):
        m._doi_metadata("10.1609/aimag.v99i9.999999")


def test_doi_resolves_without_any_metadata(web):  # boundary: it exists, nothing to compare
    table, _ = web
    table["https://doi.org/api/handles/"] = Resp(200, {"responseCode": 1})
    table["https://doi.org/"] = Resp(404)
    table["https://api.openalex.org/works/doi:"] = Resp(404)
    assert m._doi_metadata(DAVIS) == {}


def test_fallback_is_cached(web):
    table, asked = web
    table["https://doi.org/api/handles/"] = Resp(200, {"responseCode": 1})
    table["https://doi.org/"] = Resp(404)
    table["https://api.openalex.org/works/doi:"] = Resp(200, OPENALEX_DAVIS)
    m._doi_metadata(DAVIS)
    n = len(asked)
    assert m._doi_metadata(DAVIS)["title"] == "What Is a Knowledge Representation" and len(asked) == n


def test_handle_system_unreachable_is_unchecked(web):
    table, _ = web
    table["https://doi.org/api/handles/"] = Resp(503)
    table["https://doi.org/"] = Resp(404)
    with pytest.raises(m.Unchecked):
        m._doi_metadata(DAVIS)


RFC8259 = {"title": "The JavaScript Object Notation (JSON) Data Interchange Format", "type": "report",
           "issued": {"date-parts": [[2017, 12]]}}  # doi.org CSL-JSON of 10.17487/RFC8259: no author
RFC7159 = {"paperId": "p7159", "title": "The JavaScript Object Notation (JSON) Data Interchange Format"}


def bray(**fields):
    return {"ID": "bray2017json", "LINE": 1, "ENTRYTYPE": "techreport", "author": "Bray, Tim", "year": "2017",
            "title": "The {JavaScript} Object Notation ({JSON}) Data Interchange Format",
            "doi": "10.17487/RFC8259", **fields}


@pytest.fixture
def rfc(monkeypatch):
    """Title search finds RFC 7159 (2014, same title); the DOI is RFC 8259's."""
    monkeypatch.setattr(m, "_doi_metadata", lambda d: RFC8259)
    monkeypatch.setattr(m, "_candidates", lambda t, e=None: iter([RFC7159]))
    monkeypatch.setattr(m, "_get_paper_info", lambda pid: {"paperId": pid, "year": 2014,
                                                           "authors": [{"name": "T. Bray"}]})
    monkeypatch.setattr(m, "_url_for_paper", lambda p: "https://doi.org/10.17487/RFC7159")


def test_doi_confirms_the_entry(rfc):  # known-positive: was year-mismatch 2014 (RFC 7159)
    r = m.check_entry(bray())
    assert (r.url, r.findings) == ("https://doi.org/10.17487/RFC8259", [])


def test_doi_of_another_year_does_not_confirm(rfc):  # known-negative: the DOI record must agree
    r = m.check_entry(bray(year="2009"))
    assert [f.rule for f in r.findings] == ["year-mismatch"]


def test_doi_with_other_authors_does_not_confirm(monkeypatch):  # known-negative: a wrong author
    neurath = {"title": "Protokollsätze", "author": [{"given": "Otto", "family": "Neurath"}],
               "issued": {"date-parts": [[1932, 12]]}}
    monkeypatch.setattr(m, "_doi_metadata", lambda d: neurath)
    monkeypatch.setattr(m, "_candidates", lambda t, e=None: iter([{"paperId": "p", "title": "Protokollsätze"}]))
    monkeypatch.setattr(m, "_get_paper_info", lambda pid: {"paperId": pid, "year": 1932,
                                                           "authors": [{"name": "Otto Neurath"}]})
    monkeypatch.setattr(m, "_url_for_paper", lambda p: "u")
    r = m.check_entry({"ID": "n", "LINE": 1, "ENTRYTYPE": "article", "title": r'Protokolls{\"a}tze',
                       "author": "Carnap, Rudolf", "year": "1932", "doi": "10.1007/BF01886420"})
    assert [f.rule for f in r.findings] == ["authors-mismatch"]


def test_csl_names_and_year():
    csl = {"author": [{"given": "Otto", "family": "Neurath"}, {"literal": "OpenAI"}],
           "issued": {"date-parts": [[1932, 12]]}}
    assert (m._csl_names(csl), m._csl_year(csl)) == (["Otto Neurath", "OpenAI"], 1932)
    assert (m._csl_names({}), m._csl_year({})) == ([], None)
