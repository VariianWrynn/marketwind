"""I8 schema validation for Writer output (CITATION_CONTRACT §4 I8).

The Writer must emit a JSON object {claims:[...], sentences:[...]} — never
free-form text (RF-1). This validates structure and id resolution; it does NOT
judge semantics (that is the Verifier's job in P2).
"""

from __future__ import annotations

import json

from marketwind.writer.domain import DraftClaim, DraftSentence, WriterOutput

_VALID_TYPES = {"factual", "structural"}


class SchemaViolation(ValueError):
    """Raised when Writer output violates I8 (≈ RF-1: reject the whole report)."""


def parse_and_validate(
    raw: str, valid_quote_ids: set[str], valid_source_ids: set[str]
) -> WriterOutput:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise SchemaViolation(f"output is not valid JSON (free-form text?): {e}") from e
    if not isinstance(data, dict) or "claims" not in data or "sentences" not in data:
        raise SchemaViolation("output must be an object with 'claims' and 'sentences'")

    claims: list[DraftClaim] = []
    claim_ids_seen: set[str] = set()
    for c in data["claims"]:
        cid, statement, qids = c.get("id"), c.get("statement"), c.get("quote_ids")
        if not cid or not statement or not isinstance(qids, list) or not qids:
            raise SchemaViolation(f"malformed claim: {c!r}")
        unresolved = [q for q in qids if q not in valid_quote_ids]
        if unresolved:
            raise SchemaViolation(f"claim {cid} cites unknown quote_ids: {unresolved}")
        claims.append(DraftClaim(local_id=cid, statement=statement, quote_ids=list(qids)))
        claim_ids_seen.add(cid)

    sentences: list[DraftSentence] = []
    for s in data["sentences"]:
        text = s.get("sentence")
        stype = s.get("sentence_type")
        cids = s.get("claim_ids", [])
        sids = s.get("source_ids", [])
        if not text or stype not in _VALID_TYPES:
            raise SchemaViolation(f"malformed sentence: {s!r}")
        if not isinstance(cids, list) or not isinstance(sids, list):
            raise SchemaViolation(f"claim_ids/source_ids must be lists: {s!r}")
        if stype == "factual" and not cids:
            raise SchemaViolation(f"factual sentence without claim_id (Law 1): {text!r}")
        if stype == "structural" and cids:
            raise SchemaViolation(f"structural sentence carries a claim_id: {text!r}")
        bad_c = [c for c in cids if c not in claim_ids_seen]
        if bad_c:
            raise SchemaViolation(f"sentence cites unknown claim_ids: {bad_c}")
        bad_s = [x for x in sids if x not in valid_source_ids]
        if bad_s:
            raise SchemaViolation(f"sentence cites unknown source_ids: {bad_s}")
        sentences.append(
            DraftSentence(sentence=text, claim_ids=list(cids),
                          source_ids=list(sids), sentence_type=stype)
        )

    return WriterOutput(claims=claims, sentences=sentences)
