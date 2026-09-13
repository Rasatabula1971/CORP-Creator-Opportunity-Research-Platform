"""Deterministic lexical similarity for scoring.

Scoring must be reproducible from stored rows alone (same inputs → same hash),
so alignment and saturation use token overlap rather than embeddings.
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]{1,}")

STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those there here of for to in on at by
    with from as is are was were be been being am do does did doing have has had having can
    could should would will shall may might must not no nor so too very just also only own
    same such it its it's i me my we our you your he she they them their his her him who whom
    which what when where why how all any both each few more most other some into out up down
    over under again further once about between through during before after above below off
    get got want need like really much many lot lots one two thing things way make made use
    used using know think see look find help please thanks thank video comment anyone someone
    """.split()
)


def tokens(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()
    return frozenset(t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(query: frozenset[str], document: frozenset[str]) -> float:
    """Share of the query's tokens present in the document (asymmetric).

    Better than Jaccard when the document is much larger than the query, e.g.
    a cluster label against a whole shop page.
    """
    if not query or not document:
        return 0.0
    return len(query & document) / len(query)
