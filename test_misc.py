from unittest.mock import patch

import pytest

from check_hallucinations.main import MiscEntryError, _extract_url, check_misc_url


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
