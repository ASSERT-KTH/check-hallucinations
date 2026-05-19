# check-hallucinations

A command-line tool to detect hallucinated references in BibTeX files before submitting a paper to arXiv.

It checks each reference against [Semantic Scholar](https://www.semanticscholar.org/) and flags any title that cannot be found.

## Installation

```bash
pip install check-hallucinations
```

## Usage

```bash
check-hallucinations references.bib
```

Entries that cannot be found on Semantic Scholar are printed in red as potential hallucinations.

## How it works

For each entry in the BibTeX file, the tool queries Semantic Scholar by title. If no match is found, the entry is flagged as a likely hallucination (a reference invented by an LLM or a typo). `misc` entries without an `eprint` field are skipped unless they lack a `howpublished` URL.

## API key

By default the tool uses the public Semantic Scholar API (rate-limited). For higher throughput, set the `SEMANTICSCHOLAR_API_KEY` environment variable:

```bash
export SEMANTICSCHOLAR_API_KEY=your-key-here
check-hallucinations references.bib
```

## License

MIT
