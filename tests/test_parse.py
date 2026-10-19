from check_hallucinations.main import _parse

BIB = r"""
@InProceedings{real,
  Author = {Vaswani, Ashish and Shazeer, Noam},
  title = {Attention Is {All} You Need},
  year = 2017}

@misc{web, title = {SWE-bench Leaderboard}, howpublished = {\url{https://www.swebench.com}}}

@string{conf = "ICSE"}
@article{withstring, title = {T}, journal = conf}

@article{broken, title = {never closed}
"""


def test_entries_as_dicts():
    entries = _parse(BIB)
    assert [e["ID"] for e in entries] == ["real", "web", "withstring"]
    real = entries[0]
    assert real["ENTRYTYPE"] == "inproceedings"
    assert real["author"] == "Vaswani, Ashish and Shazeer, Noam"  # field names lowercased
    assert real["title"] == "Attention Is {All} You Need"  # outer braces only stripped
    assert real["year"] == "2017"
    assert entries[1]["howpublished"] == r"\url{https://www.swebench.com}"


def test_strings_resolved():  # bibtexparser 1 returned a non-str expression object here
    assert _parse(BIB)[2]["journal"] == "ICSE"


def test_empty():
    assert _parse("") == []
