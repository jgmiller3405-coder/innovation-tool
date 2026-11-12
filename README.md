# Innovation Tool

Non-generative retrieval over a fixed set of sources. Enter a prompt and get 4 verbatim
quotes (with authors, title, page or video timestamp) and 3 key sentences pulled from the
same sources. No LLM is involved at any point.

## How it works
- `sources_config.py` lists the sources (authors, titles, years). Edit it to fix any metadata.
- `build_index.py` extracts text from the PDFs, YouTube transcripts and web articles into
  `docs/passages.json`. Run from the repo root: `python build_index.py`
- `docs/index.html` is the whole app. It ranks passages in the browser with BM25 keyword
  matching. Host the `docs/` folder with GitHub Pages.

## Preview locally
```
cd docs
python -m http.server 8765
```
Then open http://localhost:8765

## Articles that block scripts
If a site refuses automated fetching (McKinsey, FTC), save the article text as
`manual/<source id>.txt` (ids are in `sources_config.py`) and re-run the build.

## Notes
- Page numbers for papers are PDF page numbers, not the journal's printed pages.
- YouTube quotes come from auto-generated captions and may contain errors.
- Matching is by keywords, so use the terms the sources use (e.g. "stablecoin", "liquidation").

## Rebuilding
Requires Python with `pymupdf`, `youtube-transcript-api`, `trafilatura` and `requests`.
Set `PDF_DIR` in `sources_config.py`, then run `python build_index.py`.
