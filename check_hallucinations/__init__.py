"""Check BibTeX references for hallucinations before submitting a paper to arXiv."""

from .main import SemanticScholarNotFound, get_url_from_title, process_bibtex_file

__all__ = ["SemanticScholarNotFound", "get_url_from_title", "process_bibtex_file"]
