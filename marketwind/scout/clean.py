"""Clean a page to frozen main-content text, then extract sentence quotes.

Span-freeze rule (spec §6): clean once, freeze the string as raw_content, and
index every span into THAT string. No re-clean / re-normalize downstream — any
mutation drifts offsets and produces phantom RF-9 failures.

Two-stage cleaning:
1. Pre-strip semantic boilerplate elements (<header>, <footer>, <nav>) with
   lxml so trafilatura's recall mode does not pull them in.
2. trafilatura extracts main-article text.

Normalization (applied once, here, before freezing):
- Collapse runs of horizontal whitespace (spaces/tabs) to a single space.
- Collapse runs of vertical whitespace (newlines) to a single newline.
- Strip leading/trailing whitespace.
The result is the frozen archive string; spans index into it permanently.
"""

from __future__ import annotations

import re

import trafilatura
from lxml import etree
from lxml import html as lxml_html

from marketwind.scout.domain import Quote
from marketwind.scout.numbers import is_quantitative

# Chinese sentence terminators (keep the terminator with the sentence).
# [^。！？]* matches any chars (including \n) up to a terminator.
_SENT = re.compile(r"[^。！？]*[。！？]")


def clean_main_content(html: str) -> str:
    """Extract main-article text. Deterministic; the result is the frozen archive.

    Pre-strips <header>, <footer>, and <nav> elements before passing to
    trafilatura so that boilerplate text (navigation, ads, footer links) is
    excluded even when favor_recall=True.
    """
    # Stage 1: remove semantic boilerplate elements.
    tree = lxml_html.fromstring(html.encode("utf-8"))
    for tag in tree.xpath("//header | //footer | //nav"):
        parent = tag.getparent()
        if parent is not None:
            parent.remove(tag)
    stripped_html = etree.tostring(tree, encoding="unicode")

    # Stage 2: trafilatura main-content extraction.
    out = trafilatura.extract(
        stripped_html,
        favor_recall=True,
        include_comments=False,
        include_tables=False,
        output_format="txt",
    )
    if not out:
        raise ValueError("main-content extraction returned empty")

    # Normalize newlines ONCE, here, before freezing.
    # Horizontal whitespace → single space; multiple newlines → single newline.
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n+", "\n", out)
    return out.strip()


def _split_sentences(raw: str) -> list[tuple[int, int, str]]:
    """Return (span_start, span_end, text) for each Chinese sentence in raw.

    Uses raw.index(text, m.start()) to re-locate the stripped text after
    stripping leading whitespace from the match, ensuring span_start points
    at the actual first character of text (not at any leading whitespace the
    regex consumed).
    """
    spans: list[tuple[int, int, str]] = []
    for m in _SENT.finditer(raw):
        text = m.group().strip()
        if not text:
            continue
        # Re-locate stripped text within THIS match window [m.start(), m.end())
        # so that (a) leading whitespace stripped from m.group() does not cause
        # offset drift, and (b) an identical sentence occurring earlier in raw
        # cannot steal the anchor (RF-9 safety: spans must point at THIS match).
        start = raw.index(text, m.start(), m.end())
        spans.append((start, start + len(text), text))
    return spans


def extract_quotes(raw: str) -> list[Quote]:
    """Extract sentence-level quotes from a frozen raw_content string.

    Every Quote's span_start / span_end indexes into raw exactly:
        raw[q.span_start : q.span_end] == q.text  (RF-9 invariant)

    context_before and context_after are the raw slices immediately before /
    after the current sentence span, so that:
        (context_before or "") + text + (context_after or "") in raw
    is always true.
    """
    sents = _split_sentences(raw)
    quotes: list[Quote] = []
    for i, (start, end, text) in enumerate(sents):
        # Use raw-slice context so before+text+after is always contiguous in raw.
        if i > 0:
            prev_start = sents[i - 1][0]
            before: str | None = raw[prev_start:start]
        else:
            before = None

        if i + 1 < len(sents):
            next_end = sents[i + 1][1]
            after: str | None = raw[end:next_end]
        else:
            after = None

        quant = is_quantitative(text)
        quotes.append(
            Quote(
                text=text,
                span_start=start,
                span_end=end,
                context_before=before,
                context_after=after,
                is_quantitative=quant,
                quote_type="data" if quant else "factual",
            )
        )
    return quotes
