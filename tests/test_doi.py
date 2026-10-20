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


def test_csl_names_and_year():
    csl = {"author": [{"given": "Otto", "family": "Neurath"}, {"literal": "OpenAI"}],
           "issued": {"date-parts": [[1932, 12]]}}
    assert (m._csl_names(csl), m._csl_year(csl)) == (["Otto Neurath", "OpenAI"], 1932)
    assert (m._csl_names({}), m._csl_year({})) == ([], None)
