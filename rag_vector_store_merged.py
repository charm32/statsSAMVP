"""
=============================================================================
 RAG Vector Store — standalone prototype (zero external dependencies)
 MERGED BUILD: rag_vector_store.py + dummy_cpi_p0141.py in a single file
=============================================================================

WHAT THIS IS
------------
A self-contained RAG (retrieval-augmented generation) pipeline you can run
and test on its own, BEFORE it is wired into main.py's existing
SEED_DOCUMENTS / PassageIndex / decide() structure.

This merged file has FOUR parts (the first three are unchanged from
rag_vector_store.py; the fourth is dummy_cpi_p0141.py folded in):

  1. DUMMY_DOCUMENTS     - the original thin synthetic fixture (3 docs,
                            2 passages each): CPI, QLFS, FAQ.
  2. VectorStore          - a small embedding + cosine-similarity index
                            (pure Python, no numpy/no external embedding
                            API).
  3. rag_loop()           - an interactive question-answer loop that ONLY
                            answers using text pulled from retrieved
                            passages, and refuses instead of guessing when
                            retrieval confidence is too low.
  4. DUMMY_CPI_RELEASE    - the richer, fictional recreation of a Stats SA
                            P0141 (CPI) release (cover page, important
                            notes, Table A, Table D, category list,
                            methodology, enquiries), formerly its own file
                            (dummy_cpi_p0141.py).

WHY THEY ARE MERGED
--------------------
So VectorStore.ingest() in this file can be shown calling directly into
DUMMY_CPI_RELEASE without a cross-file import. main() below ingests BOTH
the thin DUMMY_DOCUMENTS list AND the richer DUMMY_CPI_RELEASE document
into the same store, then runs the same three test questions the old
dummy_cpi_p0141.py used as its own standalone check — so you can see
rag_vector_store's own retrieval/scope-gate/compose_answer machinery
"calling into" the CPI fixture in one run.

EVERY NUMBER, DATE AND NAME IN DUMMY_CPI_RELEASE IS INVENTED. None of it is
the real https://www.statssa.gov.za/publications/P0141/P0141August2025.pdf
release, and it must never be treated as, cited as, or confused with real
Stats SA data. It exists only to give the vector store something
realistic-shaped to retrieve against during testing.

HOW EVERYTHING SYNTHETIC IS MARKED (same convention throughout this file)
---------------------------------------------------------------------------
  (a) IS_SYNTHETIC_TEST_DATA = True   <- a machine-checkable flag
  (b) every doc "id" is prefixed      "TEST-"
  (c) every doc has "source"          "synthetic_test_fixture"
  (d) DUMMY_CPI_RELEASE also has      "is_synthetic": True
  (e) DUMMY_CPI_RELEASE's "title" is  prefixed "[TEST] ... (fictional recreation)"
  (f) DUMMY_CPI_RELEASE's url/date    a non-resolving "*.invalid" address and
                                       a 2099 publish date
  (g) every passage's text is         prefixed "[SYNTHETIC TEST DATA]"
No real Stats SA personnel are named anywhere in this file, even
fictionally, so invented figures are never attached to a real person's name.

HOW THIS GETS "CALLED INTO" A REAL PIPELINE LATER
---------------------------------------------------------------------------
This block is intentionally kept separate from any production document
list. To use it, you EXPLICITLY ingest it — it is never auto-merged:

    store = VectorStore()
    store.ingest(DUMMY_DOCUMENTS)          # test run, thin synthetic corpus
    store.ingest([DUMMY_CPI_RELEASE])      # test run, richer synthetic doc
    # -- versus, in production --
    # store.ingest(SEED_DOCUMENTS)         # real run, approved corpus

Never merge DUMMY_DOCUMENTS or DUMMY_CPI_RELEASE into SEED_DOCUMENTS in
main.py. Keep synthetic ingestion and production ingestion as separate
instances/paths (e.g. a pytest fixture that builds its own throwaway
VectorStore).

Run it directly:
    python rag_vector_store_merged.py

No pip installs required — everything here is the standard library.
=============================================================================
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Dict, List, Tuple

IS_SYNTHETIC_TEST_DATA = True

# ---------------------------------------------------------------------------
# PART 1 — DUMMY_DOCUMENTS (thin fixture, unchanged from rag_vector_store.py)
# ---------------------------------------------------------------------------

DUMMY_DOCUMENTS: List[Dict[str, Any]] = [
    {
        "id": "TEST-P0141",
        "title": "[TEST] Consumer Price Index (CPI)",
        "product_number": "P0141",
        "doc_type": "Statistical release",
        "published": "2099-01-15",
        "url": "https://example-test.invalid/P0141",
        "theme": "Prices and inflation",
        "source": "synthetic_test_fixture",
        "passages": [
            {
                "ref": "Section 1",
                "text": "[SYNTHETIC TEST DATA] The Consumer Price Index measures the average "
                        "change over time in prices paid by consumers for a fixed basket of "
                        "goods and services.",
            },
            {
                "ref": "Table A",
                "text": "[SYNTHETIC TEST DATA] In this fabricated test release, annual consumer "
                        "price inflation was 9,9% in the reference month, purely for pipeline "
                        "testing — this is not a real figure.",
            },
        ],
    },
    {
        "id": "TEST-P0211",
        "title": "[TEST] Quarterly Labour Force Survey (QLFS)",
        "product_number": "P0211",
        "doc_type": "Statistical release",
        "published": "2099-01-10",
        "url": "https://example-test.invalid/P0211",
        "theme": "Employment and labour",
        "source": "synthetic_test_fixture",
        "passages": [
            {
                "ref": "Definitions",
                "text": "[SYNTHETIC TEST DATA] The official unemployment rate counts people who "
                        "were not employed, were available to work, and actively looked for "
                        "work in the reference period.",
            },
            {
                "ref": "Table 1",
                "text": "[SYNTHETIC TEST DATA] In this fabricated test quarter the official "
                        "unemployment rate was 11,1%, a placeholder value for testing only.",
            },
        ],
    },
    {
        "id": "TEST-FAQ",
        "title": "[TEST] Accessing test data: frequently asked questions",
        "product_number": "FAQ",
        "doc_type": "Approved FAQ",
        "published": "2099-01-01",
        "url": "https://example-test.invalid/faq",
        "theme": "Access and services",
        "source": "synthetic_test_fixture",
        "passages": [
            {
                "ref": "Downloads",
                "text": "[SYNTHETIC TEST DATA] All test releases in this fixture are published "
                        "free of charge and are available as fake PDF and Excel files for "
                        "pipeline testing.",
            },
            {
                "ref": "Contact",
                "text": "[SYNTHETIC TEST DATA] Test enquiries may be directed to "
                        "test@example.invalid. This address does not exist.",
            },
        ],
    },
    # Deliberately left thin on purpose: no document here covers GDP or
    # population. Asking about those topics against this fixture is how you
    # test that the scope gate below REFUSES instead of improvising an
    # answer from nearby-sounding passages.
]


# ---------------------------------------------------------------------------
# PART 4 — DUMMY_CPI_RELEASE (richer fixture, folded in from dummy_cpi_p0141.py)
# ---------------------------------------------------------------------------
# Kept as its own document, separate from DUMMY_DOCUMENTS above, so callers
# can choose to ingest the thin fixture, the rich one, or both — exactly as
# the original two-file layout allowed via a separate import.

DUMMY_CPI_RELEASE: Dict[str, Any] = {
    "id": "TEST-P0141-FULL",
    "title": "[TEST] Consumer Price Index (CPI) — August 2025 (fictional recreation)",
    "product_number": "P0141",
    "doc_type": "Statistical release",
    "published": "2099-09-19",
    "url": "https://example-test.invalid/P0141/P0141August2025-fictional.pdf",
    "landing_page": "https://example-test.invalid/P0141",
    "theme": "Prices and inflation",
    "source": "synthetic_test_fixture",
    "is_synthetic": True,
    "passages": [
        {
            "ref": "Cover page",
            "text": "[SYNTHETIC TEST DATA] Statistical release P0141 — Consumer Price Index, "
                    "fictional test edition modelled on an August release. Embargoed until "
                    "10:00 on the fictional release date. This cover page is fabricated for "
                    "pipeline testing and does not represent a real embargo.",
        },
        {
            "ref": "Important notes",
            "text": "[SYNTHETIC TEST DATA] For this fictional test release, Stats SA is shown "
                    "as noting that the CPI basket and weights were most recently reviewed "
                    "using a fictional income and expenditure survey. This passage exists to "
                    "test retrieval of 'basket update' style questions and contains no real "
                    "review date or methodology decision.",
        },
        {
            "ref": "Table A — Main indices",
            "text": "[SYNTHETIC TEST DATA] Fabricated Table A for testing only. "
                    "All items (CPI Headline): weight 100,00, fictional index 118,4 in the "
                    "test reference month, a fictional monthly change of 0,3% and a fictional "
                    "annual change of 5,7%. CPI excluding food, non-alcoholic beverages, fuel "
                    "and energy: fictional weight 74,40, fictional annual change 4,6%. None of "
                    "these figures are real CPI values.",
        },
        {
            "ref": "Table D — Group contributions",
            "text": "[SYNTHETIC TEST DATA] Fabricated contributions to the fictional monthly "
                    "CPI change, for testing table-style retrieval only: Food and "
                    "non-alcoholic beverages contributed a fictional 0,1 percentage points; "
                    "Housing and utilities contributed a fictional 0,1 percentage points; "
                    "Transport contributed a fictional 0,1 percentage points; Miscellaneous "
                    "goods and services contributed a fictional 0,0 percentage points; all "
                    "other groups combined contributed a fictional 0,0 percentage points.",
        },
        {
            "ref": "Basket categories",
            "text": "[SYNTHETIC TEST DATA] For testing category-lookup questions, this "
                    "fictional release lists the same twelve broad group names used in real "
                    "CPI releases, each with an invented weight: Food and non-alcoholic "
                    "beverages, Alcoholic beverages and tobacco, Clothing and footwear, "
                    "Housing, water, electricity, gas and other fuels, Household contents and "
                    "services, Health, Transport, Communication, Recreation and culture, "
                    "Education, Restaurants and hotels, and Miscellaneous goods and services. "
                    "The weight figures attached to each in this fixture are placeholders, not "
                    "real basket weights.",
        },
        {
            "ref": "Methodology (fictional)",
            "text": "[SYNTHETIC TEST DATA] This fictional release states, for testing "
                    "'how is it compiled' style questions, that prices are collected monthly "
                    "from a fictional sample of retail outlets across all provinces, and that "
                    "not every basket item is priced every month. This description is invented "
                    "for pipeline testing and is not a statement of real Stats SA fieldwork "
                    "practice.",
        },
        {
            "ref": "Enquiries (fictional)",
            "text": "[SYNTHETIC TEST DATA] For testing 'who do I contact' style questions, "
                    "this fixture lists a fictional enquiries line: "
                    "test-enquiries@example.invalid. No real Stats SA official or contact "
                    "number is referenced anywhere in this fixture.",
        },
    ],
}


# ---------------------------------------------------------------------------
# TOKENIZATION (shared by embedding + coverage checks)
# ---------------------------------------------------------------------------

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "was",
    "were", "for", "on", "at", "by", "with", "as", "that", "this", "it",
    "be", "from", "what", "how", "when", "where", "which", "who", "i",
    "we", "you", "me", "can", "do", "does", "did", "please", "tell",
    "about", "there", "their", "my", "your", "our",
}


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


# ---------------------------------------------------------------------------
# EMBEDDING — pure-Python "hashing trick" vectorizer
# ---------------------------------------------------------------------------
# No embedding model or external API call. Each token (plus its character
# trigrams, for typo/word-form tolerance) is hashed into one of EMBED_DIM
# buckets and accumulated with a signed count, then the whole vector is
# L2-normalized. This is a real, if low-fidelity, embedding technique
# (feature hashing) — good enough to prototype the RAG shape without
# pulling in numpy, sentence-transformers, or a network call.
#
# Swap-out point: replace `embed_text()` with a call to a real embedding
# model (OpenAI, sentence-transformers, etc.) later — everything downstream
# (VectorStore, cosine_similarity, rag_loop) is agnostic to how the vector
# was produced, as long as embed_text() keeps returning a List[float].
# ---------------------------------------------------------------------------

EMBED_DIM = 256


def _hash_bucket(token: str, dim: int) -> Tuple[int, int]:
    """Deterministic hash -> (bucket index, sign). Sign reduces collision bias."""
    h = hashlib.md5(token.encode("utf-8")).hexdigest()
    idx = int(h[:8], 16) % dim
    sign = 1 if int(h[8], 16) % 2 == 0 else -1
    return idx, sign


def _char_trigrams(word: str) -> List[str]:
    padded = f"#{word}#"
    if len(padded) < 3:
        return [padded]
    return [padded[i:i + 3] for i in range(len(padded) - 2)]


def embed_text(text: str, dim: int = EMBED_DIM) -> List[float]:
    vec = [0.0] * dim
    tokens = tokenize(text)
    for tok in tokens:
        idx, sign = _hash_bucket(tok, dim)
        vec[idx] += 1.0 * sign
        for tri in _char_trigrams(tok):
            idx2, sign2 = _hash_bucket(tri, dim)
            vec[idx2] += 0.3 * sign2   # lower weight: sub-word signal

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine_similarity(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))   # both already L2-normalized


# ---------------------------------------------------------------------------
# VECTOR STORE
# ---------------------------------------------------------------------------

class VectorStore:
    """
    In-memory vector index over document passages. Mirrors the shape of
    main.py's PassageIndex (doc metadata + ref + text per entry) so it can
    slot in as an alternative or companion retrieval backend later.
    """

    def __init__(self, dim: int = EMBED_DIM):
        self.dim = dim
        self.entries: List[Dict[str, Any]] = []
        self.documents: Dict[str, Dict[str, Any]] = {}

    def ingest(self, documents: List[Dict[str, Any]]) -> None:
        """Add a document list (e.g. DUMMY_DOCUMENTS, [DUMMY_CPI_RELEASE], or SEED_DOCUMENTS)."""
        for doc in documents:
            self.documents[doc["id"]] = doc
            for i, p in enumerate(doc["passages"]):
                text = p["text"]
                self.entries.append({
                    "doc_id": doc["id"],
                    "passage_id": f"{doc['id']}#{i}",
                    "ref": p["ref"],
                    "text": text,
                    "tokens": set(tokenize(text)),
                    "vector": embed_text(text, self.dim),
                })

    def search(self, query: str, top_k: int = 4) -> Dict[str, Any]:
        """
        Returns retrieved passages plus the two signals the scope gate needs:

          coverage       fraction of the query's own words that actually
                         appear in the retrieved passages (0-1)
          unknown_terms  query words present in NO ingested passage at all —
                         the strongest signal a question is out of scope
        """
        if not self.entries:
            return {"results": [], "coverage": 0.0, "unknown_terms": [], "top_sim": 0.0}

        q_tokens = tokenize(query)
        q_vec = embed_text(query, self.dim)

        corpus_vocab = set()
        for e in self.entries:
            corpus_vocab |= e["tokens"]
        unknown_terms = sorted({t for t in q_tokens if t not in corpus_vocab})

        scored = []
        for e in self.entries:
            sim = cosine_similarity(q_vec, e["vector"])
            scored.append((sim, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        if not top or top[0][0] <= 0:
            return {"results": [], "coverage": 0.0, "unknown_terms": unknown_terms, "top_sim": 0.0}

        retrieved_vocab = set()
        for _, e in top:
            retrieved_vocab |= e["tokens"]
        covered = [t for t in q_tokens if t in retrieved_vocab]
        coverage = (len(covered) / len(q_tokens)) if q_tokens else 0.0

        results = []
        for sim, e in top:
            doc = self.documents[e["doc_id"]]
            results.append({
                "passage_id": e["passage_id"],
                "doc_id": doc["id"],
                "title": doc["title"],
                "ref": e["ref"],
                "text": e["text"],
                "url": doc.get("url", ""),
                "similarity": round(sim, 3),
            })

        return {
            "results": results,
            "coverage": round(coverage, 3),
            "unknown_terms": unknown_terms,
            "top_sim": round(top[0][0], 3),
        }


# ---------------------------------------------------------------------------
# SCOPE GATE — the anti-hallucination control
# ---------------------------------------------------------------------------
# Two independent floors must both be cleared before any answer is composed.
# Either one failing means "refuse", not "do your best guess".

SIMILARITY_FLOOR = 0.12   # min cosine similarity of the best match
COVERAGE_FLOOR = 0.50     # min fraction of the question's words that must
                           # actually appear in what was retrieved


def scope_gate(query: str, retrieval: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    if not retrieval["results"]:
        reasons.append("No ingested passage matches this question at all.")
    else:
        if retrieval["top_sim"] < SIMILARITY_FLOOR:
            reasons.append(
                f"Best match similarity {retrieval['top_sim']:.2f} is below the "
                f"{SIMILARITY_FLOOR:.2f} floor."
            )
        if retrieval["coverage"] < COVERAGE_FLOOR:
            reasons.append(
                f"Retrieved passages cover only {retrieval['coverage']*100:.0f}% "
                f"of the words in the question."
            )
        if retrieval["unknown_terms"]:
            reasons.append(
                "Question mentions terms absent from the whole corpus: "
                + ", ".join(retrieval["unknown_terms"][:5]) + "."
            )
    return {"in_scope": len(reasons) == 0, "reasons": reasons}


# ---------------------------------------------------------------------------
# EXTRACTIVE ANSWER COMPOSER — no free-text generation, ever
# ---------------------------------------------------------------------------
# The answer is built ONLY out of the retrieved passage text, each line
# tagged with its citation. Nothing here invents wording, so there is no
# generation step that could hallucinate a fact.

def compose_answer(retrieval: Dict[str, Any]) -> str:
    lines = []
    for r in retrieval["results"][:3]:
        lines.append(f"- {r['text']}  [{r['title']} — {r['ref']}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# INTERACTIVE LOOP
# ---------------------------------------------------------------------------

def rag_loop(store: VectorStore) -> None:
    print("=" * 70)
    print(" RAG prototype — synthetic test corpus")
    print(f" Documents ingested : {len(store.documents)}")
    print(f" Passages indexed   : {len(store.entries)}")
    print(" Type a question, or 'quit' / 'exit' to stop.")
    print("=" * 70)

    while True:
        try:
            question = input("\nQuestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStopped.")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit"}:
            print("Stopped.")
            break

        retrieval = store.search(question)
        gate = scope_gate(question, retrieval)

        if not gate["in_scope"]:
            print("\n[REFUSED — outside what the ingested corpus supports]")
            for reason in gate["reasons"]:
                print(f"  - {reason}")
            print("  No answer has been generated, to avoid guessing.")
            continue

        print(f"\n[ANSWER — similarity {retrieval['top_sim']}, "
              f"coverage {retrieval['coverage']*100:.0f}%]")
        print(compose_answer(retrieval))


# ---------------------------------------------------------------------------
# DEMO — rag_vector_store's own machinery calling into DUMMY_CPI_RELEASE
# ---------------------------------------------------------------------------
# This replaces the old cross-file demo that lived in dummy_cpi_p0141.py's
# `if __name__ == "__main__":` block (which imported VectorStore, scope_gate,
# and compose_answer FROM rag_vector_store.py). Now it's one call graph, one
# file: VectorStore.ingest() below is handed DUMMY_CPI_RELEASE directly.

def demo_cpi_only() -> None:
    print("\n" + "#" * 70)
    print("# DEMO 1 — VectorStore ingesting ONLY DUMMY_CPI_RELEASE")
    print("#" * 70)

    store = VectorStore()
    store.ingest([DUMMY_CPI_RELEASE])   # <-- rag_vector_store calling into dummy_cpi_p0141's data

    for q in [
        "What was the headline CPI annual change in this fictional release?",
        "Which groups contributed most to the fictional monthly change?",
        "What is the mid-year population estimate?",   # deliberately out of scope
    ]:
        print("\nQ:", q)
        retrieval = store.search(q)
        gate = scope_gate(q, retrieval)
        if gate["in_scope"]:
            print(compose_answer(retrieval))
        else:
            print("[REFUSED]", "; ".join(gate["reasons"]))


def demo_combined_corpus() -> None:
    print("\n" + "#" * 70)
    print("# DEMO 2 — VectorStore ingesting DUMMY_DOCUMENTS + DUMMY_CPI_RELEASE together")
    print("#" * 70)

    store = VectorStore()
    store.ingest(DUMMY_DOCUMENTS)        # thin fixture: TEST-P0141, TEST-P0211, TEST-FAQ
    store.ingest([DUMMY_CPI_RELEASE])    # richer fixture: TEST-P0141-FULL

    for q in [
        "What was the fictional annual CPI change?",          # now two CPI-flavoured docs compete
        "What is the fictional unemployment rate?",            # only the thin QLFS doc covers this
        "Who do I contact with fictional enquiries?",           # both FAQ and CPI docs mention contacts
    ]:
        print("\nQ:", q)
        retrieval = store.search(q)
        gate = scope_gate(q, retrieval)
        if gate["in_scope"]:
            print(compose_answer(retrieval))
        else:
            print("[REFUSED]", "; ".join(gate["reasons"]))


def main() -> None:
    demo_cpi_only()
    demo_combined_corpus()

    print("\n" + "=" * 70)
    print("Demos finished. Launching interactive loop on the combined corpus.")
    print("=" * 70)
    store = VectorStore()
    store.ingest(DUMMY_DOCUMENTS)
    store.ingest([DUMMY_CPI_RELEASE])
    rag_loop(store)


if __name__ == "__main__":
    main()


# =============================================================================
# INTEGRATION NOTES — how this slots into main.py later
# =============================================================================
# main.py currently has:
#   SEED_DOCUMENTS  -> the approved corpus (same schema DUMMY_DOCUMENTS uses)
#   PassageIndex    -> BM25 keyword retrieval over SEED_DOCUMENTS
#   decide()        -> the decision gate (auto-release vs. human review)
#
# This file's VectorStore is built to the same entry shape as PassageIndex,
# so the swap is mechanical, not a rewrite:
#
#   1. INDEX = PassageIndex(SEED_DOCUMENTS)   becomes
#      INDEX = VectorStore(); INDEX.ingest(SEED_DOCUMENTS)
#      (or run BOTH and blend scores — hybrid keyword + vector retrieval —
#      by merging PassageIndex.search()'s BM25 score with this file's cosine
#      similarity per passage_id before ranking.)
#
#   2. decide() already computes `coverage` and `unknown_terms` from
#      PassageIndex.search(). scope_gate() above computes the same two
#      signals from VectorStore.search(). Either can feed decide() —
#      the field names line up on purpose.
#
#   3. compose_answer() here matches main.py's compose_answer() in spirit:
#      extractive only, one citation per line, refuse below a coverage floor
#      rather than draft something unsupported.
#
#   4. Neither DUMMY_DOCUMENTS nor DUMMY_CPI_RELEASE must ever be passed to
#      the same VectorStore/INDEX instance that also holds SEED_DOCUMENTS in
#      a running server — keep test ingestion and production ingestion as
#      separate instances/paths (e.g. a pytest fixture that builds its own
#      throwaway VectorStore).
#
#   5. Upgrade path for real embeddings without changing anything else:
#      swap embed_text() for a sentence-transformers or hosted embedding
#      call, and/or swap VectorStore's in-memory list for sqlite-vec or
#      chromadb for persistence — VectorStore.search()'s return shape can
#      stay the same, so decide()/compose_answer() don't need to change.
# =============================================================================
