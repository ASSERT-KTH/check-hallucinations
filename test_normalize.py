from check_hallucinations.main import _normalize_title


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


def test_latex_dollar_escape():
    bib = r"Fixing 55 out of 105 bugs for \$8 each"
    ss  = "Fixing 55 out of 105 bugs for $8 each"
    assert _normalize_title(bib) == _normalize_title(ss)


def test_double_dash_vs_single_dash():
    bib = "DeepSeek-Coder: When the large language model meets programming -- the rise of code intelligence"
    ss  = "DeepSeek-Coder: When the Large Language Model Meets Programming - The Rise of Code Intelligence"
    assert _normalize_title(bib) == _normalize_title(ss)
