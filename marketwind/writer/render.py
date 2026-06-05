"""Render Writer triples into a ≤500-char Chinese brief with [n] markers.

[n] is assigned here (not by the Writer) from source_ids in first-appearance
order, so a marker can never be orphaned. Over-length policy (spec §6): drop
whole trailing sentences, never truncate mid-sentence; recompute footnotes over
the kept sentences so every surviving [n] resolves.
"""

from __future__ import annotations

from marketwind.writer.domain import RenderedBrief, RenderedSentence, WriterOutput

MAX_CHARS = 500


def _render_kept(sentences) -> tuple[list[RenderedSentence], list[tuple[int, str]]]:
    """Assign [n] over the given sentences; return rendered sentences + footnotes."""
    order: list[str] = []          # source_id in first-appearance order
    rendered: list[RenderedSentence] = []
    for pos, s in enumerate(sentences):
        text = s.sentence
        if s.sentence_type == "factual":
            for sid in s.source_ids:
                if sid not in order:
                    order.append(sid)
                text += f"[{order.index(sid) + 1}]"
        rendered.append(
            RenderedSentence(
                text=text, claim_ids=list(s.claim_ids),
                source_ids=list(s.source_ids),
                sentence_type=s.sentence_type, position=pos,
            )
        )
    footnotes = [(i + 1, sid) for i, sid in enumerate(order)]
    return rendered, footnotes


def render_brief(output: WriterOutput, max_chars: int = MAX_CHARS) -> RenderedBrief:
    kept = list(output.sentences)
    while True:
        rendered, footnotes = _render_kept(kept)
        body = "".join(r.text for r in rendered)
        if len(body) <= max_chars or not kept:
            return RenderedBrief(body=body, sentences=rendered, footnotes=footnotes)
        kept.pop()  # drop the last whole sentence and re-render (markers renumber)
