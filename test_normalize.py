from check_hallucinations.main import _normalize_title, _title_matches


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


def test_title_matches_exact():
    assert _title_matches(
        "Forest before trees: The precedence of global features in visual perception",
        "Forest before trees: The precedence of global features in visual perception",
    )


def test_title_matches_trailing_star():
    # Semantic Scholar sometimes appends ☆ to titles
    assert _title_matches(
        "Forest before trees: The precedence of global features in visual perception ☆",
        "Forest before trees: The precedence of global features in visual perception",
    )


def test_title_matches_ss_main_only():
    # SS returns only main title, bib has full title with subtitle
    assert _title_matches(
        "Forest before trees",
        "Forest before trees: The precedence of global features in visual perception",
    )


def test_title_matches_bib_main_only():
    # Bib has only main title, SS returns full title with subtitle
    assert _title_matches(
        "Forest before trees: The precedence of global features in visual perception",
        "Forest before trees",
    )


def test_title_matches_period_vs_colon():
    assert _title_matches(
        "Forest before trees. The precedence of global features in visual perception",
        "Forest before trees: The precedence of global features in visual perception",
    )


def test_hyphenated_compound_word():
    # Semantic Scholar sometimes hyphenates compound words that bib titles don't
    bib = "Representation Engineering for Large Language Models: Survey and Research Challenges"
    ss  = "Representation Engineering for Large-Language Models: Survey and Research Challenges"
    assert _title_matches(ss, bib)


def test_title_matches_different():
    assert not _title_matches(
        "Something completely different",
        "Forest before trees: The precedence of global features in visual perception",
    )
