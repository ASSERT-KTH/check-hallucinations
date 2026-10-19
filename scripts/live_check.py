"""Live check of the title lookup against Semantic Scholar, arXiv and DBLP (network, not in CI).

Every entry of `corpus/real/*.bib` must be confirmed and every entry of `corpus/invented/*.bib`
reported. Prints each entry that breaks its expectation; exit 1 if any, silent otherwise.

    .venv/bin/python scripts/live_check.py [extra-real.bib ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from check_hallucinations.main import _parse_library, check_entry

CORPUS = Path(__file__).parent / "corpus"


def main(extra: list[str]) -> int:
    broken = 0
    real = sorted((CORPUS / "real").glob("*.bib")) + [Path(p) for p in extra]
    for expect_real, files in ((True, real), (False, sorted((CORPUS / "invented").glob("*.bib")))):
        for path in files:
            entries, _ = _parse_library(path.read_text())
            for entry in entries:
                findings = check_entry(entry).findings
                hallucinated = [f for f in findings if f.rule != "unchecked"]
                if expect_real and hallucinated:
                    for f in hallucinated:
                        print(f"{path}:{f.line}: real entry reported: {f.rule}: {f.key}: {f.message}")
                    broken += 1
                elif not expect_real and not hallucinated:
                    print(f"{path}:{entry['LINE']}: invented entry confirmed: {entry['ID']}")
                    broken += 1
                for f in findings:
                    if f.rule == "unchecked":
                        print(f"{path}:{f.line}: unchecked: {f.key}: {f.message}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
