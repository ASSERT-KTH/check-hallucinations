from check_hallucinations.main import _normalize_title, _title_word_jaccard


def test_colon_vs_period_subtitle():
    # bib uses ': ' as subtitle separator, SS uses '. '
    bib = "Code reviews do not find bugs: How the current code review best practice slows us down"
    ss  = "Code Reviews Do Not Find Bugs. How the Current Code Review Best Practice Slows Us Down"
    assert _normalize_title(bib) == _normalize_title(ss)


def test_exact_match():
    assert _normalize_title("Foo Bar") == _normalize_title("foo bar")


def test_diacritics():
    assert _normalize_title("Über cool") == _normalize_title("Uber cool")


def test_curly_braces():
    assert _normalize_title("{Foo} Bar") == _normalize_title("Foo Bar")


def test_word_jaccard_hyphen_split():
    # bib: "real-GitHub" splits as "real"+"github"; SS has "Real-World GitHub"
    # all bib words are in SS → Jaccard 0.9
    bib = "SWE-bench: Can language models resolve real-GitHub issues?"
    ss  = "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?"
    assert _title_word_jaccard(bib, ss) >= 0.85
