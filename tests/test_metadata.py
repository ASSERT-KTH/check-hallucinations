import pytest

from check_hallucinations._metadata import authors_mismatch, bib_last_names, year_mismatch

VASWANI = ["Ashish Vaswani", "Noam Shazeer", "N. Parmar", "J. Uszkoreit"]


@pytest.mark.parametrize("field,names", [
    ("Vaswani, Ashish and Shazeer, Noam", ["vaswani", "shazeer"]),
    ("Ashish Vaswani and Noam Shazeer and others", ["vaswani", "shazeer"]),
    ("van der Aalst, Wil M. P.", ["van der aalst"]),
    ("M{\\\"u}ller, Hans", ["muller"]),
    ("{OpenAI}", ["openai"]),
    ("", []),
])
def test_bib_last_names(field, names):
    assert bib_last_names(field) == names


def test_same_authors():  # known-negative
    assert authors_mismatch("Vaswani, Ashish and Shazeer, Noam and Parmar, Niki", VASWANI) is None


def test_invented_authors():  # known-positive: a real title with invented authors
    assert authors_mismatch("Smith, John and Doe, Jane", VASWANI) == "first author smith is not an author"


def test_most_authors_absent():
    why = authors_mismatch("Vaswani, A. and Smith, J. and Doe, J. and Roe, R.", VASWANI)
    assert why == "3 of 4 authors are not authors"


@pytest.mark.parametrize("field,names", [
    ("Vaswani, A. and Smith, J.", VASWANI),                   # boundary: half present
    ("Vaswani, Ashish and others", VASWANI),                  # et al.
    ("M{\\\"u}ller, Hans", ["Hans Müller"]),                  # LaTeX accent against Unicode
    ("van der Aalst, Wil", ["Wil M. P. van der Aalst"]),     # particle
    ("Smith-Jones, Ann", ["Ann Smith-Jones"]),
    ("Smith, John", []),                                      # nothing to compare with
])
def test_tolerated(field, names):
    assert authors_mismatch(field, names) is None


@pytest.mark.parametrize("bib,found,mismatch", [
    ("2017", 2017, False),
    ("2016", 2017, False),       # a preprint a year before its venue
    ("2016", 2018, False),       # boundary: a TSE 2016 paper dated 2018 by Semantic Scholar
    ("2015", 2018, True),
    ("{2009}", 2017, True),
    ("in press", 2017, False),   # unknown year
    ("2017", None, False),
])
def test_year(bib, found, mismatch):
    assert (year_mismatch(bib, found) is not None) == mismatch
