from unittest.mock import patch

import pytest

from check_hallucinations.main import MiscEntryError, _extract_url, check_entry, check_misc_url


def test_extract_url_latex():
    assert _extract_url(r"\url{https://example.com}") == "https://example.com"


def test_extract_url_plain():
    assert _extract_url("https://example.com") == "https://example.com"


def test_extract_url_missing():
    assert _extract_url("no url here") is None


@patch("check_hallucinations.main._fetch_page_title")
def test_check_misc_url_match(mock_fetch):
    mock_fetch.return_value = "SWE-bench Leaderboard | Official Site"
    check_misc_url("https://www.swebench.com", "SWE-bench Leaderboard")


@patch("check_hallucinations.main._fetch_page_title")
def test_check_misc_url_mismatch(mock_fetch):
    mock_fetch.return_value = "Some Completely Different Page"
    with pytest.raises(MiscEntryError, match="Title does not match"):
        check_misc_url("https://www.swebench.com", "SWE-bench Leaderboard")


@patch("check_hallucinations.main._fetch_page_title")
def test_check_misc_url_no_title(mock_fetch):
    mock_fetch.return_value = ""
    with pytest.raises(MiscEntryError, match="No <title>"):
        check_misc_url("https://example.com", "Some Title")


@patch("check_hallucinations.main._fetch_page_title")
def test_check_misc_url_colon_uses_subtitle(mock_fetch):
    # Page shows only the subtitle; the "Main: " prefix is not in the HTML title
    mock_fetch.return_value = "The Official Leaderboard | SWE-bench"
    check_misc_url(
        "https://www.swebench.com",
        "SWE-bench: The Official Leaderboard",
    )


@patch("check_hallucinations.main._fetch_page_title")
def test_check_misc_url_colon_wrong_subtitle(mock_fetch):
    mock_fetch.return_value = "Some Unrelated Page Title"
    with pytest.raises(MiscEntryError, match="Title does not match"):
        check_misc_url(
            "https://example.com",
            "My Blog: Adventures in Python",
        )


def _misc(**fields):
    return {"ID": "k", "LINE": 1, "ENTRYTYPE": "misc", "title": "Guilty Statements", **fields}


@patch("check_hallucinations.main._fetch_page_title")
def test_url_field_is_checked(mock_fetch):  # known-positive: was no-url
    mock_fetch.return_value = "Hilary Putnam · Guilty Statements"
    url = "https://www.lrb.co.uk/the-paper/v06/n08/hilary-putnam/guilty-statements"
    r = check_entry(_misc(howpublished="London Review of Books, 6(8)", url=url))
    assert (r.url, r.findings) == (url, [])
    mock_fetch.assert_called_once_with(url)


@patch("check_hallucinations.main._fetch_page_title")
def test_url_field_wrong_page(mock_fetch):  # known-negative: the url field is checked, not trusted
    mock_fetch.return_value = "Some Completely Different Page"
    r = check_entry(_misc(url="https://example.com/x"))
    assert [f.rule for f in r.findings] == ["web-mismatch"]


def test_no_url_anywhere():  # boundary: neither url nor howpublished
    r = check_entry(_misc(howpublished="London Review of Books"))
    assert [f.rule for f in r.findings] == ["no-url"]
