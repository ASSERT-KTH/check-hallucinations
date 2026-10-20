from unittest.mock import patch

import pytest

from check_hallucinations import main as m
from check_hallucinations.main import MiscEntryError, _extract_url, check_entry, check_misc_url


def page(title, text=""):
    """A patch of `_fetch_page`: a web page with this <title> and this visible text."""
    return patch.object(m, "_fetch_page", return_value={"title": title, "text": text})


def test_extract_url_latex():
    assert _extract_url(r"\url{https://example.com}") == "https://example.com"


def test_extract_url_plain():
    assert _extract_url("https://example.com") == "https://example.com"


def test_extract_url_missing():
    assert _extract_url("no url here") is None


def test_check_misc_url_match():
    with page("SWE-bench Leaderboard | Official Site"):
        check_misc_url("https://www.swebench.com", "SWE-bench Leaderboard")


def test_check_misc_url_mismatch():
    with page("Some Completely Different Page"), pytest.raises(MiscEntryError, match="Title does not match"):
        check_misc_url("https://www.swebench.com", "SWE-bench Leaderboard")


def test_check_misc_url_no_title():
    with page(""), pytest.raises(MiscEntryError, match="No <title>"):
        check_misc_url("https://example.com", "Some Title")


def test_check_misc_url_colon_uses_subtitle():
    # Page shows only the subtitle; the "Main: " prefix is not in the HTML title
    with page("The Official Leaderboard | SWE-bench"):
        check_misc_url("https://www.swebench.com", "SWE-bench: The Official Leaderboard")


def test_check_misc_url_colon_wrong_subtitle():
    with page("Some Unrelated Page Title"), pytest.raises(MiscEntryError, match="Title does not match"):
        check_misc_url("https://example.com", "My Blog: Adventures in Python")


TOML_TEXT = "TOML v1.0.0 Tom's Obvious, Minimal Language. By Tom Preston-Werner, Pradyun Gedam, et al."


def test_title_in_page_text():  # known-positive: the <title> is "TOML: English v1.0.0"
    with page("TOML: English v1.0.0", TOML_TEXT):
        check_misc_url("https://toml.io/en/v1.0.0", "{TOML} v1.0.0: Tom's Obvious, Minimal Language")


def test_title_partly_in_page_text():  # known-negative: every part of the title must be on the page
    with page("TOML: English v1.0.0", TOML_TEXT), pytest.raises(MiscEntryError, match="Title does not match"):
        check_misc_url("https://toml.io/en/v1.0.0", "TOML v1.0.0: Tom's Obvious, Maximal Language")


def test_title_words_scattered_in_page_text():  # boundary: words present, not as a phrase
    text = "Language design is minimal. Tom found it obvious."
    with page("Blog", text), pytest.raises(MiscEntryError):
        check_misc_url("https://example.com", "Tom's Obvious, Minimal Language")


def test_page_text_extraction(monkeypatch, tmp_path):
    html = ("<html><head><title>TOML: English v1.0.0</title><style>h1 {color: red}</style></head>"
            "<body><h1 id='toml-v100'>TOML v1.0.0</h1>\n<p>Tom&#39;s Obvious, Minimal Language.</p>"
            "<script>var x = 'Hidden';</script></body></html>")

    class Resp:
        text = html

        def raise_for_status(self):
            pass

    monkeypatch.setattr(m, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Resp())
    got = m._fetch_page("https://toml.io/en/v1.0.0")
    assert got["title"] == "TOML: English v1.0.0"
    assert "Tom's Obvious, Minimal Language." in got["text"] and "Hidden" not in got["text"]
    assert m._fetch_page_title("https://toml.io/en/v1.0.0") == "TOML: English v1.0.0"


def _misc(**fields):
    return {"ID": "k", "LINE": 1, "ENTRYTYPE": "misc", "title": "Guilty Statements", **fields}


def test_url_field_is_checked():  # known-positive: was no-url
    url = "https://www.lrb.co.uk/the-paper/v06/n08/hilary-putnam/guilty-statements"
    with page("Hilary Putnam · Guilty Statements") as fetch:
        r = check_entry(_misc(howpublished="London Review of Books, 6(8)", url=url))
    assert (r.url, r.findings) == (url, [])
    fetch.assert_called_once_with(url)


def test_url_field_wrong_page():  # known-negative: the url field is checked, not trusted
    with page("Some Completely Different Page"):
        r = check_entry(_misc(url="https://example.com/x"))
    assert [f.rule for f in r.findings] == ["web-mismatch"]


def test_no_url_anywhere():  # boundary: neither url nor howpublished
    r = check_entry(_misc(howpublished="London Review of Books"))
    assert [f.rule for f in r.findings] == ["no-url"]
