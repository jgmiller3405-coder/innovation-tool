"""Build docs/passages.json (the searchable index) from the fixed source list.

Run from the repo root:  uv run python innovation-tool/build_index.py

Nothing here generates text: it only extracts verbatim passages and records
where each one came from (page number or video timestamp).

Articles that block automated fetching (e.g. McKinsey, FTC) can be supplied by
saving the page text to innovation-tool/manual/<source id>.txt.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf
import requests
import trafilatura
from youtube_transcript_api import YouTubeTranscriptApi

sys.path.insert(0, str(Path(__file__).parent))
from sources_config import PDF_DIR, SOURCES  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "docs"
MANUAL = HERE / "manual"
UA = {"User-Agent": "InnovationToolBuilder/1.0 (personal research index builder)"}

ABBREV = r"(?<!\bet al)(?<!\be\.g)(?<!\bi\.e)(?<!\bFig)(?<!\bEq)(?<!\bU\.S)(?<!\bvs)(?<!\bNo)(?<!\bDr)"
SENT_SPLIT = re.compile(ABBREV + r"(?<=[.!?])\s+(?=[A-Z“\"(\[])")


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub("[\u00ad\u200b\u200c\u200d\ufeff]", "", text)  # soft hyphen, zero-width chars
    text = re.sub(r"([a-z]{3}[.!?])(?=[A-Z][a-z])", r"\1 ", text)  # "reliance.Regulatory" -> two sentences
    text = re.sub(r"-\n(?=[a-z])", "", text)  # de-hyphenate line breaks
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


BOILERPLATE = ("ai-powered", "table of contents", "sign up", "newsletter", "advertis", "learn more",
               "read more", "working paper no", "discussion paper", "staff report", "mimeo",
               "ssrn", "nber", "forthcoming", "unpublished", "manuscript", "journal of ",
               "quarterly journal", "econometrica", "proceedings of", "university press",
               "bank for international settlements", "(eds.)", "this table", "this figure",
               "the table reports", "the figure plots", "table notes")
REF_LIKE = re.compile(r"\b(19|20)\d{2}[a-z]?\)?[.,]\s*[\"“]|^[A-Z][a-z]+,\s+[A-Z]\.|\bpp?\.\s*\d|\bvol\.\s*\d|\b\d+\s*\(\d+\)\s*[:,]")


def good_sentence(s: str) -> bool:
    if not (40 <= len(s) <= 700):
        return False
    letters = sum(c.isalpha() for c in s)
    digits = sum(c.isdigit() for c in s)
    if letters / len(s) < 0.75 or digits / len(s) > 0.08:
        return False
    low = s.lower()
    if any(b in low for b in ("downloaded from", "all rights reserved", "electronic copy available",
                              "http://", "https://", "doi.org", "@", "cookie", "subscribe", "copyright")):
        return False
    if any(b in low for b in BOILERPLATE) or REF_LIKE.search(s):
        return False
    if not s.rstrip().endswith((".", "!", "?", '"', "”", ")")):
        return False
    return len(s.split()) >= 10


def windows(sents, size=3, step=2):
    """Overlapping windows of consecutive sentences."""
    out = []
    for i in range(0, max(len(sents), 1), step):
        chunk = sents[i:i + size]
        if chunk:
            out.append(chunk)
        if i + size >= len(sents):
            break
    return out


def passages_from_sentences(src, sents, loc_fn):
    res = []
    for w in windows(sents):
        quote = " ".join(s for s, _ in w)
        if 120 <= len(quote) <= 900:
            res.append(dict(src=src["id"], text=quote, loc=loc_fn(w[0][1]),
                            sents=[s for s, _ in w]))
    return res


def split_sentences(text):
    out = []
    for s in SENT_SPLIT.split(text):
        # drop a leading page marker / section heading such as "ii Abstract " or "Introduction "
        s = re.sub(r"^(?:[ivxl]+\s+)?(?:Abstract|Introduction)\s+(?=[A-Z])", "", s.strip())
        if s:
            out.append(s)
    return out


# ---------- PDFs ----------
def extract_pdf(src):
    path = Path(PDF_DIR) / src["file"]
    doc = pymupdf.open(path)
    n = len(doc)
    stop_page = n
    for i in range(n):  # drop references/bibliography onward (only in the back half)
        if i < n * 0.4:
            continue
        for line in doc[i].get_text().splitlines():
            if line.strip().lower() in ("references", "bibliography", "literature cited"):
                stop_page = i
                break
        if stop_page != n:
            break
    pairs = []
    for i in range(stop_page + 1 if stop_page < n else n):
        txt = clean(doc[i].get_text())
        for s in split_sentences(txt):
            if good_sentence(s):
                pairs.append((s, i + 1))
    return passages_from_sentences(src, pairs, lambda p: dict(kind="page", page=p))


# ---------- Videos ----------
def extract_video(src):
    snippets = list(YouTubeTranscriptApi().fetch(src["video_id"], languages=["en", "en-US", "en-GB"]))
    words = []
    for sn in snippets:
        t = re.sub(r"\[[^\]]*\]", " ", sn.text)  # [Music] etc.
        for w in t.split():
            words.append((w, sn.start))
    res, size, step = [], 70, 55
    for i in range(0, len(words), step):
        chunk = words[i:i + size]
        if len(chunk) < 30:
            break
        text = " ".join(w for w, _ in chunk)
        res.append(dict(src=src["id"], text=text, sents=[text],
                        loc=dict(kind="time", seconds=int(chunk[0][1]))))
    return res


# ---------- Articles ----------
def extract_article(src):
    manual = MANUAL / f"{src['id']}.txt"
    if manual.exists():
        text = manual.read_text(encoding="utf-8")
    else:
        r = requests.get(src["url"], headers=UA, timeout=45)
        r.raise_for_status()
        text = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
        if len(text) < 1500:
            raise RuntimeError(f"only {len(text)} chars extracted")
    pairs = []
    for para in re.split(r"\n\s*\n|\n", text):
        if para.lstrip().startswith(("- ", "• ", "* ")):  # bullet/glossary fragments
            continue
        for s in split_sentences(clean(para)):
            if good_sentence(s):
                pairs.append((s, None))
    return passages_from_sentences(src, pairs, lambda _: dict(kind="web"))


def main():
    OUT.mkdir(exist_ok=True)
    MANUAL.mkdir(exist_ok=True)
    all_passages, report, skipped = [], [], []
    for src in SOURCES:
        try:
            fn = dict(paper=extract_pdf, video=extract_video, article=extract_article)[src["type"]]
            ps = fn(src)
            if not ps:
                raise RuntimeError("no passages extracted")
            all_passages.extend(ps)
            report.append(f"OK    {src['id']:<28} {len(ps):>5} passages")
        except Exception as e:  # keep going; report at the end
            skipped.append(src["id"])
            report.append(f"SKIP  {src['id']:<28} {type(e).__name__}: {str(e)[:90]}")
    for i, p in enumerate(all_passages):
        p["id"] = i
    meta = []
    for s in SOURCES:
        m = {k: v for k, v in s.items() if k not in ("file",)}
        if s["type"] == "video":
            m["url"] = f"https://www.youtube.com/watch?v={s['video_id']}"
        meta.append(m)
    (OUT / "passages.json").write_text(
        json.dumps(dict(sources=meta, passages=all_passages), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    print("\n".join(report))
    print(f"\n{len(all_passages)} passages from {len(SOURCES) - len(skipped)}/{len(SOURCES)} sources")


if __name__ == "__main__":
    main()
