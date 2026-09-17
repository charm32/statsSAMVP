"""
=============================================================================
 Stats SA - AI-Enabled Assistant for Public and Media Information Queries
 Minimum Viable Product (MVP)  |  Single-file, zero-dependency Python backend
=============================================================================

WHAT THIS IS
------------
A working demonstration of the challenge solution:

    public / media question
        -> understand the question
        -> retrieve from APPROVED Stats SA sources only
        -> compose a cited, plain-language answer
        -> DECISION GATE: auto-answer, or escalate to a human
        -> reviewer approves / edits / rejects
        -> approved answer is written back to a reusable repository

HOW TO RUN (VS Code)
--------------------
    1. Put this file in a folder, open the folder in VS Code.
    2. Select a Python 3.9+ interpreter.
    3. Run:   python main.py
    4. Open:  http://127.0.0.1:8000
    5. Reviewer console key (demo):  statssa-demo-key

    No pip install required. Standard library only.

IMPORTANT - ABOUT THE DATA
--------------------------
The corpus below is a SMALL SAMPLE built to exercise the pipeline. Publication
names, product numbers (P0141, P0211, P0441 ...) and URL patterns follow
www.statssa.gov.za, but THE PASSAGE TEXT AND FIGURES ARE ILLUSTRATIVE
PLACEHOLDERS WRITTEN FOR THIS DEMO. They are not published Stats SA values.

Before any real use, replace SEED_DOCUMENTS with text ingested from the actual
releases. See the ingestion note at the bottom of this file.
=============================================================================
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

HOST = "127.0.0.1"
PORT = 8000
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statssa_mvp.db")

# Demo role-based access control. In production this becomes SSO / OIDC with
# groups mapped to roles (public, media_desk, reviewer, knowledge_admin).
REVIEWER_API_KEY = "statssa-demo-key"

# Decision gate thresholds - configurable, as the design requires.
AUTO_ANSWER_MIN_SCORE = 0.42     # retrieval confidence floor for auto-release
AUTO_ANSWER_MIN_PASSAGES = 2     # supporting passages needed for auto-release
REUSE_MIN_SCORE = 0.55           # similarity floor to recommend a past answer

# Terms that force human review no matter how confident retrieval is.
# (Sensitivity / reputational screen from the design brief.)
SENSITIVITY_TERMS = [
    "election", "minister", "president", "political", "party", "anc", "da ",
    "eff", "corruption", "scandal", "lying", "manipulat", "fake", "cover up",
    "cover-up", "protest", "strike", "crisis", "failure", "incompetent",
    "comment on", "respond to", "react to", "allegation", "criticism",
    "why did stats sa", "is stats sa", "accused", "blame", "opinion",
    "forecast", "predict", "will the", "should the", "budget speech",
]

# Question shapes that need interpretation or judgement -> human review.
INTERPRETIVE_PATTERNS = [
    r"\bwhy\b", r"\bdo you think\b", r"\bwhat does .* mean for\b",
    r"\bimplication", r"\bcause", r"\bexplain why\b", r"\bcompare .* to other countries\b",
]


# ---------------------------------------------------------------------------
# 1. APPROVED KNOWLEDGE BASE  (the only thing the assistant may read)
# ---------------------------------------------------------------------------
# Each document = one approved Stats SA source.
# Each passage = one retrievable, citable chunk of that source.
#
# *** SAMPLE TEXT - REPLACE WITH REAL INGESTED CONTENT BEFORE USE ***

SEED_DOCUMENTS: List[Dict[str, Any]] = [
    {
        "id": "P0141",
        "title": "Consumer Price Index (CPI)",
        "product_number": "P0141",
        "doc_type": "Statistical release",
        "published": "2025-08-20",
        "url": "https://www.statssa.gov.za/publications/P0141/P0141August2025.pdf",
        "landing_page": "https://www.statssa.gov.za/?page_id=1854&PPN=P0141",
        "theme": "Prices and inflation",
        "passages": [
            {
                "ref": "Section 1",
                "text": "The Consumer Price Index measures the average change over time in the "
                        "prices paid by consumers for a fixed basket of goods and services. "
                        "Headline CPI is the main measure of consumer price inflation in South Africa "
                        "and is used by the South African Reserve Bank for inflation targeting.",
            },
            {
                "ref": "Table A",
                "text": "[SAMPLE FIGURE] In this illustrative release, annual consumer price inflation "
                        "was 4,1% in the reference month, compared with 4,0% in the preceding month. "
                        "The monthly change in the CPI was 0,2%.",
            },
            {
                "ref": "Section 3",
                "text": "The CPI basket is reweighted periodically using the Income and Expenditure Survey. "
                        "Not all items in the basket are surveyed every month; a detailed survey schedule "
                        "of items not priced monthly is published in Table F of the monthly release.",
            },
            {
                "ref": "Release calendar",
                "text": "The Consumer Price Index is published monthly, usually in the third week of the "
                        "month following the reference month, and is embargoed until 10:00 on the release date.",
            },
        ],
    },
    {
        "id": "P0211",
        "title": "Quarterly Labour Force Survey (QLFS)",
        "product_number": "P0211",
        "doc_type": "Statistical release",
        "published": "2025-08-12",
        "url": "https://www.statssa.gov.za/publications/P0211/P02112ndQuarter2025.pdf",
        "landing_page": "https://www.statssa.gov.za/?page_id=1854&PPN=P0211",
        "theme": "Employment and labour",
        "passages": [
            {
                "ref": "Definitions",
                "text": "The official unemployment rate counts people aged 15 to 64 who were not employed "
                        "in the reference week, were available to work, and actively looked for work or "
                        "tried to start a business in the four weeks before the interview. "
                        "The expanded definition also includes discouraged work-seekers who wanted to work "
                        "but did not actively search.",
            },
            {
                "ref": "Table 1",
                "text": "[SAMPLE FIGURE] In this illustrative quarter the official unemployment rate was 32,9%, "
                        "and the expanded unemployment rate was 42,9%. The number of employed persons was "
                        "approximately 17,1 million.",
            },
            {
                "ref": "Methodology",
                "text": "The Quarterly Labour Force Survey is a household-based sample survey covering "
                        "approximately 30 000 dwelling units across all nine provinces. Results are weighted "
                        "to the mid-year population estimates and are subject to sampling error.",
            },
            {
                "ref": "Youth",
                "text": "[SAMPLE FIGURE] Youth aged 15 to 34 remain the most affected by unemployment. "
                        "In this illustrative quarter the unemployment rate among young people aged 15 to 24 "
                        "was 60,8%.",
            },
        ],
    },
    {
        "id": "P0441",
        "title": "Gross Domestic Product (GDP)",
        "product_number": "P0441",
        "doc_type": "Statistical release",
        "published": "2025-09-02",
        "url": "https://www.statssa.gov.za/publications/P0441/P04412ndQuarter2025.pdf",
        "landing_page": "https://www.statssa.gov.za/?page_id=1854&PPN=P0441",
        "theme": "Economic growth",
        "passages": [
            {
                "ref": "Table 2",
                "text": "[SAMPLE FIGURE] In this illustrative quarter, real gross domestic product increased "
                        "by 0,3% quarter-on-quarter, seasonally adjusted. The finance, manufacturing and "
                        "agriculture industries were the largest positive contributors to growth.",
            },
            {
                "ref": "Revisions policy",
                "text": "Preliminary GDP growth rates are published approximately nine weeks after the end of "
                        "the reference quarter. Preliminary values are revised in the following quarter using "
                        "updated source data, so figures from earlier releases may be superseded.",
            },
            {
                "ref": "Method",
                "text": "GDP is compiled at constant 2015 prices and is presented both seasonally adjusted and "
                        "unadjusted. The production, expenditure and income approaches are used, with the "
                        "production approach forming the headline estimate.",
            },
        ],
    },
    {
        "id": "P0302",
        "title": "Mid-year population estimates",
        "product_number": "P0302",
        "doc_type": "Statistical release",
        "published": "2025-07-22",
        "url": "https://www.statssa.gov.za/publications/P0302/P03022025.pdf",
        "landing_page": "https://www.statssa.gov.za/?page_id=1854&PPN=P0302",
        "theme": "Population",
        "passages": [
            {
                "ref": "Key results",
                "text": "[SAMPLE FIGURE] For this illustrative year, the mid-year population of South Africa is "
                        "estimated at 63,0 million people. Gauteng is estimated to be the province with the "
                        "largest share of the population, followed by KwaZulu-Natal.",
            },
            {
                "ref": "Method",
                "text": "Mid-year population estimates are produced using the cohort-component method, which "
                        "combines the latest census base with assumptions about fertility, mortality and migration. "
                        "Estimates are revised when new census or survey data become available.",
            },
        ],
    },
    {
        "id": "CENSUS2022",
        "title": "Census 2022 Statistical Release",
        "product_number": "03-01-22",
        "doc_type": "Census release",
        "published": "2023-10-10",
        "url": "https://www.statssa.gov.za/publications/P03014/P030142022.pdf",
        "landing_page": "https://www.statssa.gov.za/?page_id=3839",
        "theme": "Population",
        "passages": [
            {
                "ref": "Overview",
                "text": "Census 2022 was South Africa's fourth post-apartheid population census and the first "
                        "conducted primarily using digital data collection. It enumerated households across all "
                        "provinces and provides the base population for subsequent estimates.",
            },
            {
                "ref": "Undercount",
                "text": "A Post-Enumeration Survey is conducted after every census to measure coverage. "
                        "The census results are adjusted for the measured undercount before publication, "
                        "and the adjustment method is documented in the technical report.",
            },
        ],
    },
    {
        "id": "P0142.1",
        "title": "Producer Price Index (PPI)",
        "product_number": "P0142.1",
        "doc_type": "Statistical release",
        "published": "2025-08-28",
        "url": "https://www.statssa.gov.za/publications/P01421/P01421August2025.pdf",
        "landing_page": "https://www.statssa.gov.za/?page_id=1854&PPN=P0142.1",
        "theme": "Prices and inflation",
        "passages": [
            {
                "ref": "Scope",
                "text": "The Producer Price Index measures price changes received by domestic producers for "
                        "their output, before the goods reach the consumer. It differs from the Consumer Price "
                        "Index, which measures prices paid by households.",
            },
            {
                "ref": "Table 1",
                "text": "[SAMPLE FIGURE] In this illustrative release, annual producer price inflation for "
                        "final manufactured goods was 3,2%.",
            },
        ],
    },
    {
        "id": "FAQ-ACCESS",
        "title": "Accessing Stats SA data: frequently asked questions",
        "product_number": "FAQ",
        "doc_type": "Approved FAQ",
        "published": "2025-06-01",
        "url": "https://www.statssa.gov.za/?page_id=1866",
        "landing_page": "https://www.statssa.gov.za/?page_id=1866",
        "theme": "Access and services",
        "passages": [
            {
                "ref": "Downloads",
                "text": "All Stats SA statistical releases are published free of charge on www.statssa.gov.za. "
                        "Releases are available as PDF documents and, for most products, as accompanying Excel "
                        "workbooks containing the published tables.",
            },
            {
                "ref": "Microdata",
                "text": "Anonymised microdata from household surveys is available through the Stats SA data portal "
                        "under the conditions of the Statistics Act, which prohibits the release of information "
                        "that could identify an individual respondent or business.",
            },
            {
                "ref": "Contact",
                "text": "General enquiries may be directed to info@statssa.gov.za or +27 12 310 8911. "
                        "Stats SA is located at ISIbalo House, Koch Street, Salvokop, Pretoria.",
            },
            {
                "ref": "Citation",
                "text": "When using Stats SA figures, users should cite the product number, publication title "
                        "and reference period, for example: Statistics South Africa, Consumer Price Index, P0141.",
            },
        ],
    },
    {
        "id": "RELEASE-CAL",
        "title": "Scheduled publications and release calendar",
        "product_number": "CALENDAR",
        "doc_type": "Organisational information",
        "published": "2025-09-01",
        "url": "https://www.statssa.gov.za/?page_id=1874",
        "landing_page": "https://www.statssa.gov.za/?page_id=1874",
        "theme": "Access and services",
        "passages": [
            {
                "ref": "Advance calendar",
                "text": "Stats SA publishes an advance release calendar listing the scheduled date of every "
                        "statistical release. Release dates are announced in advance and all releases are "
                        "embargoed until 10:00 on the publication date, in line with international good practice.",
            },
            {
                "ref": "Products",
                "text": "Scheduled products include the Consumer Price Index (P0141), Producer Price Index "
                        "(P0142.1), Quarterly Labour Force Survey (P0211), Gross Domestic Product (P0441), "
                        "Retail trade sales (P6242.1), Mining production and sales (P2041) and Manufacturing "
                        "production and sales (P3041.2).",
            },
        ],
    },
    {
        "id": "STYLE-GUIDE",
        "title": "Stats SA communication style and terminology guide",
        "product_number": "INTERNAL-COMMS",
        "doc_type": "Communication guideline",
        "published": "2025-05-15",
        "url": "https://www.statssa.gov.za/?page_id=1866",
        "landing_page": "https://www.statssa.gov.za/?page_id=1866",
        "theme": "Communication standards",
        "internal_only": True,   # not shown to the public channel
        "passages": [
            {
                "ref": "Tone",
                "text": "Stats SA communications are factual, neutral and non-speculative. Responses describe "
                        "what the published statistics show and avoid interpretation of policy, prediction of "
                        "future outcomes, or commentary on the performance of any institution.",
            },
            {
                "ref": "Terminology",
                "text": "Always state the reference period with any figure. Use 'official unemployment rate' or "
                        "'expanded unemployment rate' explicitly rather than 'unemployment' alone. Refer to the "
                        "organisation as 'Stats SA' or 'Statistics South Africa', never 'StatsSA'.",
            },
        ],
    },
    {
        "id": "MEDIA-2025-04",
        "title": "Media statement: interpretation of revised GDP estimates",
        "product_number": "MEDIA",
        "doc_type": "Approved media statement",
        "published": "2025-06-10",
        "url": "https://www.statssa.gov.za/?p=17000",
        "landing_page": "https://www.statssa.gov.za/?page_id=1859",
        "theme": "Economic growth",
        "passages": [
            {
                "ref": "Statement",
                "text": "Stats SA notes that revisions to preliminary GDP estimates are a routine part of national "
                        "accounts compilation and reflect the incorporation of more complete source data. "
                        "Revisions are published in accordance with the documented revisions policy and do not "
                        "indicate an error in the earlier estimate.",
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# 2. RETRIEVAL ENGINE  (BM25 over approved passages - no external libraries)
# ---------------------------------------------------------------------------

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "was", "were",
    "for", "on", "at", "by", "with", "as", "that", "this", "it", "be", "from",
    "what", "how", "when", "where", "which", "who", "i", "we", "you", "me",
    "can", "do", "does", "did", "please", "tell", "about", "there", "their",
    "my", "your", "our", "s", "sa", "stats", "statssa", "much", "many", "so",
    "between", "each", "why", "because", "like", "other", "more", "most",
    "any", "all", "some", "into", "over", "per", "also", "get", "give", "want",
    "know", "need", "would", "could", "should", "have", "has", "had", "if",
    "will", "go", "up", "down", "me", "us", "am", "been", "being",
}


def stem(token: str) -> str:
    """
    Crude prefix stemmer. 'released', 'release' and 'releases' all become
    'relea', so a question asking when something is released matches a passage
    saying when it is published monthly. Good enough for an MVP; swap for a
    proper stemmer or embeddings later.
    """
    return token[:5] if len(token) > 5 else token

# Question shape -> extra search terms. Cheap intent handling: "when is X
# released" should reach the release calendar, not the latest figure table.
QUERY_HINTS: List[Tuple[str, List[str]]] = [
    (r"\bwhen\b|\brelease date\b|\bschedule\b|\bpublished\b|\bhow often\b",
     ["calendar", "scheduled", "published", "monthly", "embargoed", "release", "date"]),
    (r"\bdefin|\bwhat is the difference\b|\bdiffer|\bmean(s|ing)?\b|\bhow is .* (defined|measured|calculated)\b",
     ["definition", "measures", "differs", "counts", "scope"]),
    (r"\bmethod|\bhow .* (compiled|produced|collected)\b|\bsample\b|\bsurvey\b",
     ["methodology", "method", "compiled", "sample", "weighted"]),
    (r"\bdownload|\bget\b|\baccess\b|\bfree\b|\bwhere can i\b",
     ["publications", "website", "free", "excel", "portal"]),
    (r"\bcontact|\bphone|\bemail|\baddress\b",
     ["enquiries", "info", "telephone", "pretoria"]),
]

SYNONYMS = {
    "inflation": ["cpi", "consumer", "price", "index"],
    "cpi": ["inflation", "consumer", "price"],
    "jobs": ["employment", "employed", "labour", "unemployment"],
    "unemployment": ["labour", "qlfs", "jobless", "employment"],
    "jobless": ["unemployment", "labour"],
    "economy": ["gdp", "growth", "domestic", "product"],
    "growth": ["gdp", "economy"],
    "gdp": ["growth", "economy", "domestic", "product"],
    "population": ["census", "people", "residents", "estimates"],
    "census": ["population", "enumerated"],
    "download": ["publications", "releases", "website", "free"],
    "contact": ["enquiries", "email", "telephone"],
    "youth": ["young", "15", "24", "34"],
    "provinces": ["gauteng", "kwazulu-natal", "provincial"],
}


def tokenize(text: str, keep_original: bool = False):
    """
    Lowercase, strip punctuation, drop stopwords, stem.
    With keep_original=True also returns {stem: original word} so messages to
    users can name the actual word they typed rather than a truncated stem.
    """
    words = re.findall(r"[a-z0-9,\.\-]+", text.lower())
    out: List[str] = []
    originals: Dict[str, str] = {}
    for w in words:
        w = w.strip(".,-")
        if not w or w in STOPWORDS or len(w) < 2:
            continue
        s = stem(w)
        out.append(s)
        originals.setdefault(s, w)
    if keep_original:
        return out, originals
    return out


def _stem_table():
    """Synonym and hint tables are written in plain words; stem them once."""
    syn = {}
    for k, vals in SYNONYMS.items():
        syn.setdefault(stem(k), set()).update(stem(v) for v in vals)
    hints = [(pat, [stem(t) for t in toks]) for pat, toks in QUERY_HINTS]
    return syn, hints


def expand_query(question: str) -> Tuple[Dict[str, float], List[str]]:
    """
    Build weighted search terms.

    Returns (weighted_terms, base_tokens).
    Base tokens are the user's own words and carry full weight; synonyms and
    intent hints carry less, so an expansion can help ranking but can never
    make up for the user's actual words being absent from the corpus.
    """
    base, originals = tokenize(question, keep_original=True)
    weighted: Dict[str, float] = {t: 1.0 for t in base}

    for t in base:
        for s in STEMMED_SYNONYMS.get(t, ()):
            if s not in weighted:
                weighted[s] = 0.45

    ql = question.lower()
    for pattern, extra in STEMMED_HINTS:
        if re.search(pattern, ql):
            for s in extra:
                if s not in weighted:
                    weighted[s] = 0.7

    expand_query.last_originals = originals   # used for readable gate messages
    return weighted, base


STEMMED_SYNONYMS, STEMMED_HINTS = _stem_table()


class PassageIndex:
    """
    A small BM25 index. Each entry is one passage of one approved document.
    In production this layer becomes a hybrid keyword + vector store
    (for example PostgreSQL with pgvector, or OpenSearch).
    """

    K1 = 1.5
    B = 0.75

    def __init__(self, documents: List[Dict[str, Any]]):
        self.entries: List[Dict[str, Any]] = []
        self.documents = {d["id"]: d for d in documents}

        for doc in documents:
            for i, p in enumerate(doc["passages"]):
                tokens = tokenize(p["text"] + " " + doc["title"] + " " + doc["theme"])
                self.entries.append({
                    "doc_id": doc["id"],
                    "passage_id": f"{doc['id']}#{i}",
                    "ref": p["ref"],
                    "text": p["text"],
                    "tokens": tokens,
                    "length": len(tokens),
                })

        self.avg_len = sum(e["length"] for e in self.entries) / max(len(self.entries), 1)
        self.df: Dict[str, int] = {}
        for e in self.entries:
            for term in set(e["tokens"]):
                self.df[term] = self.df.get(term, 0) + 1
        self.n = len(self.entries)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 4, include_internal: bool = False
               ) -> Dict[str, Any]:
        """
        Returns results plus the diagnostics the decision gate needs:

          coverage      how much of what the user actually asked is present in
                        the retrieved passages (0-1)
          unknown_terms the user's words that appear in NO approved source -
                        the strongest signal that a question is out of scope
        """
        weighted, base = expand_query(query)
        empty = {"results": [], "coverage": 0.0, "unknown_terms": [], "top_raw": 0.0}
        if not weighted:
            return empty

        # Words the corpus has never seen. "Mars" in a question about
        # population must not be silently ignored. Reported in the user's own
        # wording, and only for content-bearing words.
        originals = getattr(expand_query, "last_originals", {})
        unknown = [
            originals.get(t, t) for t in dict.fromkeys(base)
            if self.df.get(t, 0) == 0
            and t not in STEMMED_SYNONYMS      # known domain word, just phrased differently
            and not t.isdigit() and len(t) >= 3
        ]

        scored = []
        for e in self.entries:
            doc = self.documents[e["doc_id"]]
            if doc.get("internal_only") and not include_internal:
                continue

            tf_counts: Dict[str, int] = {}
            for t in e["tokens"]:
                tf_counts[t] = tf_counts.get(t, 0) + 1

            score = 0.0
            for term, weight in weighted.items():
                tf = tf_counts.get(term, 0)
                if tf == 0:
                    continue
                num = tf * (self.K1 + 1)
                den = tf + self.K1 * (1 - self.B + self.B * e["length"] / self.avg_len)
                score += weight * self._idf(term) * (num / den)

            if score > 0:
                scored.append((score, e, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        if not top:
            return {"results": [], "coverage": 0.0, "unknown_terms": unknown, "top_raw": 0.0}

        # Coverage: of the user's own words, weighted by how informative each
        # one is, how many actually appear in the passages we are about to use?
        retrieved_vocab = set()
        for _, e, _d in top[:3]:
            retrieved_vocab.update(e["tokens"])

        total_w, found_w = 0.0, 0.0
        for t in set(base):
            w = self._idf(t) if self.df.get(t, 0) else 2.5   # unseen term = costly
            total_w += w
            if t in retrieved_vocab:
                found_w += w
        coverage = (found_w / total_w) if total_w else 0.0

        best = top[0][0]
        results = []
        for raw, e, doc in top:
            results.append({
                "passage_id": e["passage_id"],
                "doc_id": doc["id"],
                "title": doc["title"],
                "product_number": doc["product_number"],
                "doc_type": doc["doc_type"],
                "published": doc["published"],
                "url": doc["url"],
                "ref": e["ref"],
                "text": e["text"],
                "raw_score": round(raw, 3),
                "score": round(raw / (best + 1e-9), 3),   # relative rank only
            })

        return {
            "results": results,
            "coverage": round(coverage, 3),
            "unknown_terms": unknown,
            "top_raw": round(best, 3),
        }


INDEX = PassageIndex(SEED_DOCUMENTS)


# ---------------------------------------------------------------------------
# 3. QUESTION UNDERSTANDING + DECISION GATE
# ---------------------------------------------------------------------------

def screen_question(question: str) -> Dict[str, Any]:
    """Sensitivity and interpretation screen, run before anything is released."""
    q = question.lower()
    hits = [t.strip() for t in SENSITIVITY_TERMS if t in q]
    interpretive = [p for p in INTERPRETIVE_PATTERNS if re.search(p, q)]
    return {
        "sensitive": bool(hits),
        "sensitivity_terms": hits[:5],
        "interpretive": bool(interpretive),
    }


def decide(channel: str, question: str, retrieval: Dict[str, Any]) -> Dict[str, Any]:
    """
    THE DECISION GATE.

    Auto-release only when ALL of these hold:
      - the channel is public (media is ALWAYS routed to a human)
      - the question is not sensitive and not interpretive
      - every meaningful word in the question is covered by approved sources
      - retrieval strength and coverage both clear their thresholds
    """
    screen = screen_question(question)
    results = retrieval["results"]
    coverage = retrieval["coverage"]
    unknown = retrieval["unknown_terms"]

    # Strength of the best match, flattened into 0-1.
    match_strength = min(retrieval["top_raw"] / 6.0, 1.0) if results else 0.0
    # Confidence is deliberately coverage-dominated: a strong match on the
    # wrong question must not score highly.
    confidence = round(coverage * match_strength, 3)
    supporting = len([r for r in results if r["score"] >= 0.45])

    reasons: List[str] = []
    if channel == "media":
        reasons.append("Media channel: responses are never issued automatically.")
    if screen["sensitive"]:
        reasons.append(
            "Sensitivity screen triggered ("
            + ", ".join(screen["sensitivity_terms"]) + ")."
        )
    if screen["interpretive"]:
        reasons.append("Question asks for interpretation or judgement.")
    if not results:
        reasons.append("No approved source covers this question.")
    else:
        if unknown:
            reasons.append(
                "Question refers to terms that appear in no approved source: "
                + ", ".join(unknown[:5]) + "."
            )
        if coverage < 0.55:
            reasons.append(
                f"Approved sources cover only {coverage*100:.0f}% of the question."
            )
        if confidence < AUTO_ANSWER_MIN_SCORE:
            reasons.append(
                f"Confidence {confidence:.2f} is below the "
                f"{AUTO_ANSWER_MIN_SCORE:.2f} release threshold."
            )
        if supporting < AUTO_ANSWER_MIN_PASSAGES:
            reasons.append("Fewer than two strong supporting passages; coverage is thin.")

    return {
        "auto_release": len(reasons) == 0,
        "confidence": confidence,
        "coverage": coverage,
        "match_strength": round(match_strength, 3),
        "unknown_terms": unknown,
        "supporting_passages": supporting,
        "reasons": reasons,
        "screen": screen,
    }


# ---------------------------------------------------------------------------
# 4. ANSWER COMPOSITION  (extractive - grounded by construction)
# ---------------------------------------------------------------------------
# This MVP quotes approved passages and frames them, rather than generating
# free text. That makes hallucination structurally impossible. If you later
# add a language model, keep the same contract: it may only rephrase the
# passages passed to it, and every sentence keeps its citation.

GAP_COVERAGE_FLOOR = 0.40   # below this, refuse rather than draft


def compose_answer(question: str, results: List[Dict[str, Any]],
                   gate: Dict[str, Any]) -> Dict[str, Any]:
    if not results:
        return {
            "answer": "",
            "gap": True,
            "gap_note": (
                "No approved Stats SA source in the knowledge base covers this question. "
                "No response has been generated, to avoid unsupported content."
            ),
            "citations": [],
        }

    # Information gap: the retrieved passages do not actually address what was
    # asked. Refuse rather than return something adjacent and plausible.
    if gate["coverage"] < GAP_COVERAGE_FLOOR:
        note = (
            f"Approved sources address only {gate['coverage']*100:.0f}% of this question"
        )
        if gate["unknown_terms"]:
            note += (" and contain nothing on: " + ", ".join(gate["unknown_terms"][:5]))
        note += (". No wording has been generated. Refer to the responsible division "
                 "or extend the approved knowledge base.")
        return {"answer": "", "gap": True, "gap_note": note, "citations": []}

    used = [r for r in results if r["score"] >= 0.45][:3] or results[:1]

    paragraphs = []
    for i, r in enumerate(used, start=1):
        paragraphs.append(f"{r['text']} [{i}]")

    citations = [{
        "n": i,
        "title": r["title"],
        "product_number": r["product_number"],
        "doc_type": r["doc_type"],
        "reference": r["ref"],
        "published": r["published"],
        "url": r["url"],
    } for i, r in enumerate(used, start=1)]

    return {
        "answer": "\n\n".join(paragraphs),
        "gap": False,
        "gap_note": "",
        "citations": citations,
    }


def build_draft(question: str, answer: Dict[str, Any], gate: Dict[str, Any],
                requester: str) -> str:
    """Structured draft for a communications official to review."""
    lines = [
        "DRAFT RESPONSE - NOT FOR ISSUE WITHOUT APPROVAL",
        "",
        f"Query received: {question}",
        f"From: {requester or 'not supplied'}",
        "",
        "Suggested response:",
        "",
    ]
    if answer["gap"]:
        lines.append(
            "No approved source material covers this query. Recommend that the "
            "responsible division be consulted before any response is issued. "
            "No draft wording has been generated."
        )
    else:
        lines.append(answer["answer"])
        lines.append("")
        lines.append("Sources used:")
        for c in answer["citations"]:
            lines.append(f"  [{c['n']}] {c['title']} ({c['product_number']}), "
                         f"{c['reference']}, published {c['published']}")
            lines.append(f"      {c['url']}")
    lines += [
        "",
        "Why this was escalated:",
    ]
    for r in gate["reasons"]:
        lines.append(f"  - {r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. STORAGE  (SQLite: review queue, approved repository, audit log)
# ---------------------------------------------------------------------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS queries (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            channel TEXT,
            requester TEXT,
            question TEXT,
            status TEXT,              -- answered | pending_review | approved | rejected
            confidence REAL,
            gate_reasons TEXT,
            draft TEXT,
            citations TEXT,
            reviewer TEXT,
            reviewed_at TEXT,
            final_text TEXT
        );

        CREATE TABLE IF NOT EXISTS repository (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            question TEXT,
            answer TEXT,
            citations TEXT,
            approved_by TEXT,
            source_query_id TEXT,
            version INTEGER
        );

        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT,
            actor TEXT,
            action TEXT,
            detail TEXT
        );
        """)


def audit(actor: str, action: str, detail: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO audit (at, actor, action, detail) VALUES (?,?,?,?)",
            (now(), actor, action, detail),
        )


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# 6. RESPONSE REUSE  (communication memory)
# ---------------------------------------------------------------------------

def find_reusable(question: str) -> Optional[Dict[str, Any]]:
    """Look for a previously approved answer to a similar question."""
    q_tokens = set(tokenize(question))
    if not q_tokens:
        return None

    best, best_score = None, 0.0
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM repository ORDER BY created_at DESC"
        ).fetchall()

    for row in rows:
        r_tokens = set(tokenize(row["question"]))
        if not r_tokens:
            continue
        overlap = len(q_tokens & r_tokens) / len(q_tokens | r_tokens)  # Jaccard
        if overlap > best_score:
            best, best_score = row, overlap

    if best is not None and best_score >= REUSE_MIN_SCORE:
        return {
            "id": best["id"],
            "question": best["question"],
            "answer": best["answer"],
            "citations": json.loads(best["citations"] or "[]"),
            "approved_by": best["approved_by"],
            "approved_at": best["created_at"],
            "similarity": round(best_score, 2),
        }
    return None


# ---------------------------------------------------------------------------
# 7. CORE PIPELINE
# ---------------------------------------------------------------------------

def handle_query(question: str, channel: str, requester: str = "") -> Dict[str, Any]:
    question = (question or "").strip()
    if len(question) < 5:
        return {"error": "Please enter a question of at least 5 characters."}

    qid = "Q-" + uuid.uuid4().hex[:8].upper()
    started = time.time()

    # Step 1: has an approved answer already been given to something similar?
    reuse = find_reusable(question)

    # Step 2: retrieve from approved sources (internal sources only for media desk)
    retrieval = INDEX.search(question, top_k=4, include_internal=(channel == "media"))
    results = retrieval["results"]

    # Step 3: gate
    gate = decide(channel, question, retrieval)

    # Step 4: compose
    answer = compose_answer(question, results, gate)

    citations_json = json.dumps(answer["citations"])
    elapsed = round((time.time() - started) * 1000)

    if gate["auto_release"]:
        status = "answered"
        draft = ""
    else:
        status = "pending_review"
        draft = build_draft(question, answer, gate, requester)

    with db() as conn:
        conn.execute(
            """INSERT INTO queries
               (id, created_at, channel, requester, question, status, confidence,
                gate_reasons, draft, citations, reviewer, reviewed_at, final_text)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (qid, now(), channel, requester, question, status, gate["confidence"],
             json.dumps(gate["reasons"]), draft, citations_json, None, None, None),
        )
    audit(channel, "query_received", f"{qid} | status={status} | conf={gate['confidence']}")

    return {
        "query_id": qid,
        "channel": channel,
        "status": status,
        "auto_release": gate["auto_release"],
        "confidence": gate["confidence"],
        "coverage": gate["coverage"],
        "match_strength": gate["match_strength"],
        "reasons": gate["reasons"],
        "answer": answer["answer"] if gate["auto_release"] else "",
        "gap": answer["gap"],
        "gap_note": answer["gap_note"],
        "citations": answer["citations"],
        "retrieved": [{"title": r["title"], "ref": r["ref"], "score": r["score"]}
                      for r in results],
        "reuse": reuse,
        "elapsed_ms": elapsed,
        "disclaimer": (
            "Wording assembled from published Stats SA sources listed below. "
            "Verify against the linked source before quoting."
        ),
    }


def list_reviews() -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM queries WHERE status='pending_review' ORDER BY created_at DESC"
        ).fetchall()
    return [{
        "id": r["id"], "created_at": r["created_at"], "channel": r["channel"],
        "requester": r["requester"], "question": r["question"],
        "confidence": r["confidence"],
        "reasons": json.loads(r["gate_reasons"] or "[]"),
        "draft": r["draft"],
        "citations": json.loads(r["citations"] or "[]"),
    } for r in rows]


def approve(qid: str, final_text: str, reviewer: str) -> Dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM queries WHERE id=?", (qid,)).fetchone()
        if row is None:
            return {"error": "Query not found."}
        if row["status"] != "pending_review":
            return {"error": f"Query is already {row['status']}."}

        conn.execute(
            "UPDATE queries SET status='approved', reviewer=?, reviewed_at=?, final_text=? WHERE id=?",
            (reviewer, now(), final_text, qid),
        )
        rid = "R-" + uuid.uuid4().hex[:8].upper()
        conn.execute(
            """INSERT INTO repository
               (id, created_at, question, answer, citations, approved_by, source_query_id, version)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, now(), row["question"], final_text, row["citations"], reviewer, qid, 1),
        )
    audit(reviewer, "approved", f"{qid} -> repository {rid}")
    return {"ok": True, "query_id": qid, "repository_id": rid,
            "message": "Approved and written back to the reusable repository."}


def reject(qid: str, note: str, reviewer: str) -> Dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM queries WHERE id=?", (qid,)).fetchone()
        if row is None:
            return {"error": "Query not found."}
        conn.execute(
            "UPDATE queries SET status='rejected', reviewer=?, reviewed_at=?, final_text=? WHERE id=?",
            (reviewer, now(), note, qid),
        )
    audit(reviewer, "rejected", f"{qid} | {note[:120]}")
    return {"ok": True, "message": "Rejected. Nothing was published or stored for reuse."}


def repository_list() -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM repository ORDER BY created_at DESC").fetchall()
    return [{
        "id": r["id"], "created_at": r["created_at"], "question": r["question"],
        "answer": r["answer"], "approved_by": r["approved_by"],
        "citations": json.loads(r["citations"] or "[]"),
    } for r in rows]


def audit_list(limit: int = 60) -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def source_list() -> List[Dict[str, Any]]:
    return [{
        "id": d["id"], "title": d["title"], "product_number": d["product_number"],
        "doc_type": d["doc_type"], "published": d["published"], "url": d["url"],
        "theme": d["theme"], "passages": len(d["passages"]),
        "internal_only": bool(d.get("internal_only")),
    } for d in SEED_DOCUMENTS]


def stats() -> Dict[str, Any]:
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM queries").fetchone()["c"]
        auto = conn.execute("SELECT COUNT(*) c FROM queries WHERE status='answered'").fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) c FROM queries WHERE status='pending_review'").fetchone()["c"]
        approved = conn.execute("SELECT COUNT(*) c FROM queries WHERE status='approved'").fetchone()["c"]
        repo = conn.execute("SELECT COUNT(*) c FROM repository").fetchone()["c"]
    return {"total_queries": total, "auto_answered": auto, "pending_review": pending,
            "approved": approved, "repository_entries": repo,
            "documents": len(SEED_DOCUMENTS),
            "passages": len(INDEX.entries)}


# ---------------------------------------------------------------------------
# 8. FRONTEND  (served from this same file)
# ---------------------------------------------------------------------------

FRONTEND = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stats SA AI assistant - MVP</title>
<style>
:root{--ink:#131a2e;--soft:#59617e;--page:#eef1f7;--panel:#fff;--line:#d3daea;
--green:#0f8a72;--amber:#e08a1e;--red:#d23b4e;--blue:#3f4fc4;--gold:#f0b429}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 18px 70px}
header h1{margin:0;font-size:1.5rem;letter-spacing:-.02em}
header p{margin:6px 0 0;color:var(--soft);font-size:.92rem;max-width:62ch}
.warn{margin:16px 0 0;padding:10px 14px;border-radius:8px;font-size:.85rem;
 background:#fff6e5;border:1px solid var(--gold);color:#6b4b00}
nav{display:flex;gap:6px;flex-wrap:wrap;margin:22px 0 18px;border-bottom:1px solid var(--line)}
nav button{font:inherit;font-size:.92rem;font-weight:600;background:none;border:none;cursor:pointer;
 padding:10px 14px;color:var(--soft);border-bottom:3px solid transparent}
nav button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--green)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:14px}
h2{font-size:1.05rem;margin:0 0 4px}
.hint{color:var(--soft);font-size:.87rem;margin:0 0 14px}
textarea,input{font:inherit;width:100%;padding:10px 12px;border:1px solid var(--line);
 border-radius:8px;background:var(--panel);color:var(--ink)}
textarea{min-height:82px;resize:vertical}
label{display:block;font-size:.84rem;font-weight:600;margin:10px 0 5px;color:var(--soft)}
button.go{font:inherit;font-weight:600;cursor:pointer;margin-top:12px;padding:10px 18px;border-radius:8px;
 border:none;background:var(--green);color:#fff}
button.go.alt{background:var(--blue)} button.go.danger{background:var(--red)}
button.go:disabled{opacity:.5;cursor:default}
.ex{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.ex button{font:inherit;font-size:.8rem;cursor:pointer;padding:5px 10px;border-radius:100px;
 border:1px solid var(--line);background:var(--page);color:var(--soft)}
.badge{display:inline-block;font-size:.76rem;font-weight:700;padding:3px 9px;border-radius:100px;color:#fff}
.b-auto{background:var(--green)} .b-rev{background:var(--amber)} .b-gap{background:var(--red)}
.ans{white-space:pre-wrap;margin:12px 0;padding:14px;border-radius:8px;
 background:#f0faf7;border-left:4px solid var(--green)}
.draftbox{white-space:pre-wrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.82rem;
 padding:12px;border-radius:8px;background:#fdf6e9;border-left:4px solid var(--amber);margin:10px 0}
.cites{margin:10px 0 0;padding:0;list-style:none;font-size:.86rem}
.cites li{padding:8px 0;border-top:1px dashed var(--line)}
.cites a{color:var(--blue)}
.why{margin:10px 0 0;padding:10px 14px;border-radius:8px;background:#fdecef;border:1px solid var(--red);font-size:.86rem}
.why b{color:var(--red)}
.why ul{margin:6px 0 0;padding-left:18px}
.meta{font-size:.8rem;color:var(--soft);margin-top:10px}
.reuse{margin-top:12px;padding:10px 14px;border-radius:8px;background:#eef0ff;border:1px solid var(--blue);font-size:.86rem}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.8rem;color:var(--soft)}
.kpi{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.kpi div{flex:1 1 120px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi b{display:block;font-size:1.5rem;line-height:1.2}
.kpi span{font-size:.78rem;color:var(--soft)}
.item{border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}
.item h3{margin:0 0 4px;font-size:.98rem}
.item .sub{font-size:.8rem;color:var(--soft)}
.empty{color:var(--soft);font-size:.9rem;padding:8px 0}
</style></head><body><div class="wrap">

<header>
<h1>Stats SA AI assistant &mdash; working MVP</h1>
<p>Public self-service answers from approved sources, media queries routed to a human, and every approved answer stored for reuse.</p>
<div class="warn"><b>Sample corpus.</b> Publication titles, product numbers and links follow statssa.gov.za, but passage text and figures in this demo are illustrative placeholders, not published Stats SA values.</div>
</header>

<nav role="tablist">
<button role="tab" data-tab="public" aria-selected="true">Public assistant</button>
<button role="tab" data-tab="media" aria-selected="false">Media desk</button>
<button role="tab" data-tab="review" aria-selected="false">Reviewer console</button>
<button role="tab" data-tab="repo" aria-selected="false">Approved repository</button>
<button role="tab" data-tab="sources" aria-selected="false">Knowledge base</button>
<button role="tab" data-tab="audit" aria-selected="false">Audit log</button>
</nav>

<!-- PUBLIC -->
<section id="tab-public">
 <div class="panel">
  <h2>Ask about South African official statistics</h2>
  <p class="hint">Factual, well-covered questions are answered immediately with citations. Anything sensitive, interpretive or poorly covered is escalated to a Stats SA official instead.</p>
  <textarea id="pq" placeholder="For example: What is the difference between the official and expanded unemployment rate?"></textarea>
  <div class="ex" id="pex"></div>
  <button class="go" id="pbtn">Ask</button>
  <div id="pout"></div>
 </div>
</section>

<!-- MEDIA -->
<section id="tab-media" hidden>
 <div class="panel">
  <h2>Submit a media query</h2>
  <p class="hint">Media queries are never answered automatically. A referenced draft is prepared for a communications official to review and approve.</p>
  <label for="mwho">Your name and publication</label>
  <input id="mwho" placeholder="e.g. T. Mokoena, Business Day">
  <label for="mq">Query</label>
  <textarea id="mq" placeholder="e.g. Can Stats SA comment on the revisions to the latest GDP estimate?"></textarea>
  <button class="go alt" id="mbtn">Submit query</button>
  <div id="mout"></div>
 </div>
</section>

<!-- REVIEW -->
<section id="tab-review" hidden>
 <div class="panel">
  <h2>Reviewer console</h2>
  <p class="hint">Role-restricted. Edit the draft, then approve or reject. Approval writes the final wording into the reusable repository; rejection stores nothing.</p>
  <label for="rkey">Reviewer API key</label>
  <input id="rkey" value="statssa-demo-key">
  <label for="rname">Reviewer name</label>
  <input id="rname" value="Comms Official">
  <button class="go" id="rload">Load review queue</button>
  <div id="rout"></div>
 </div>
</section>

<!-- REPO -->
<section id="tab-repo" hidden>
 <div class="panel"><h2>Approved communication repository</h2>
 <p class="hint">Every approved response, searchable and reusable. The assistant checks here first on every new query.</p>
 <button class="go" id="repoload">Refresh</button><div id="repoout"></div></div>
</section>

<!-- SOURCES -->
<section id="tab-sources" hidden>
 <div class="panel"><h2>Approved knowledge base</h2>
 <p class="hint">The only material the assistant may read. Internal-only items are hidden from the public channel.</p>
 <div id="srcout"></div></div>
</section>

<!-- AUDIT -->
<section id="tab-audit" hidden>
 <div class="panel"><h2>Audit log</h2>
 <p class="hint">Who asked what, what the gate decided, who approved it.</p>
 <button class="go" id="auload">Refresh</button><div id="auout"></div></div>
</section>

</div>
<script>
const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

// tabs
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.setAttribute('aria-selected', String(x===b)));
  document.querySelectorAll('section').forEach(s => s.hidden = true);
  $('#tab-' + b.dataset.tab).hidden = false;
  if (b.dataset.tab === 'review') loadReviews();
  if (b.dataset.tab === 'repo') loadRepo();
  if (b.dataset.tab === 'sources') loadSources();
  if (b.dataset.tab === 'audit') loadAudit();
});

async function api(path, opts){ const r = await fetch(path, opts); return r.json(); }

// examples
const EXAMPLES = [
  "How is the official unemployment rate defined?",
  "When is the CPI released each month?",
  "What is the difference between CPI and PPI?",
  "Where can I download Stats SA publications for free?",
  "Why is the unemployment rate so high?",
  "Can Stats SA comment on the minister's remarks about the economy?"
];
$('#pex').innerHTML = EXAMPLES.map(e => `<button type="button">${esc(e)}</button>`).join('');
$('#pex').onclick = e => { if (e.target.tagName==='BUTTON'){ $('#pq').value = e.target.textContent; ask(); } };

function citeHtml(cs){
  if (!cs.length) return '';
  return '<ul class="cites">' + cs.map(c =>
   `<li>[${c.n}] <a href="${c.url}" target="_blank" rel="noopener">${esc(c.title)}</a>
    (${esc(c.product_number)}) &mdash; ${esc(c.reference)}, published ${esc(c.published)}</li>`).join('') + '</ul>';
}

function renderResult(d, forMedia){
  if (d.error) return `<div class="why"><b>${esc(d.error)}</b></div>`;
  let h = '';
  if (d.reuse) h += `<div class="reuse"><b>Previously approved answer found</b> (similarity ${d.reuse.similarity}).
    Approved by ${esc(d.reuse.approved_by)} on ${esc(d.reuse.approved_at)}.<br><br>${esc(d.reuse.answer)}</div>`;

  if (d.auto_release){
    h += `<p style="margin-top:14px"><span class="badge b-auto">Answered automatically</span>
      <span class="meta">confidence ${d.confidence} &middot; ${d.elapsed_ms} ms &middot; ${esc(d.query_id)}</span></p>`;
    h += `<div class="ans">${esc(d.answer)}</div>`;
    h += `<p class="meta">${esc(d.disclaimer)}</p>` + citeHtml(d.citations);
  } else {
    const badge = d.gap ? '<span class="badge b-gap">Information gap</span>'
                        : '<span class="badge b-rev">Escalated for human review</span>';
    h += `<p style="margin-top:14px">${badge}
      <span class="meta">confidence ${d.confidence} &middot; ${esc(d.query_id)}</span></p>`;
    if (d.gap) h += `<div class="why"><b>No supported answer generated.</b><br>${esc(d.gap_note)}</div>`;
    h += `<div class="why"><b>Why this was not answered automatically</b><ul>` +
         d.reasons.map(r => `<li>${esc(r)}</li>`).join('') + `</ul></div>`;
    if (d.citations.length) h += `<p class="meta">Draft prepared for review, referencing:</p>` + citeHtml(d.citations);
    h += `<p class="meta">Open the reviewer console to see and approve the draft.</p>`;
  }
  return h;
}

async function ask(){
  const q = $('#pq').value.trim(); if (!q) return;
  $('#pbtn').disabled = true; $('#pout').innerHTML = '<p class="meta">Searching approved sources...</p>';
  const d = await api('/api/query', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({question:q, channel:'public'})});
  $('#pout').innerHTML = renderResult(d, false); $('#pbtn').disabled = false;
}
$('#pbtn').onclick = ask;

$('#mbtn').onclick = async () => {
  const q = $('#mq').value.trim(); if (!q) return;
  $('#mbtn').disabled = true; $('#mout').innerHTML = '<p class="meta">Preparing draft...</p>';
  const d = await api('/api/query', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({question:q, channel:'media', requester:$('#mwho').value})});
  $('#mout').innerHTML = renderResult(d, true); $('#mbtn').disabled = false;
};

async function loadReviews(){
  const d = await api('/api/reviews', {headers:{'X-API-Key': $('#rkey').value}});
  if (d.error){ $('#rout').innerHTML = `<div class="why"><b>${esc(d.error)}</b></div>`; return; }
  if (!d.items.length){ $('#rout').innerHTML = '<p class="empty">Nothing waiting for review.</p>'; return; }
  $('#rout').innerHTML = d.items.map(i => `
    <div class="item">
      <h3>${esc(i.question)}</h3>
      <p class="sub">${esc(i.id)} &middot; ${esc(i.channel)} channel &middot; ${esc(i.requester||'no requester')}
       &middot; confidence ${i.confidence} &middot; ${esc(i.created_at)}</p>
      <div class="why"><b>Escalation reasons</b><ul>${i.reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul></div>
      <label>Draft (editable before approval)</label>
      <textarea id="d-${i.id}" style="min-height:190px;font-family:ui-monospace,monospace;font-size:.8rem">${esc(i.draft)}</textarea>
      <button class="go" onclick="decide('${i.id}','approve')">Approve and store</button>
      <button class="go danger" onclick="decide('${i.id}','reject')">Reject</button>
    </div>`).join('');
}
$('#rload').onclick = loadReviews;

async function decide(id, action){
  const text = $('#d-'+id).value;
  const d = await api(`/api/reviews/${id}/${action}`, {method:'POST',
    headers:{'Content-Type':'application/json','X-API-Key':$('#rkey').value},
    body: JSON.stringify({text: text, reviewer: $('#rname').value})});
  alert(d.message || d.error || 'Done');
  loadReviews();
}

async function loadRepo(){
  const d = await api('/api/repository');
  $('#repoout').innerHTML = d.items.length ? d.items.map(i => `
    <div class="item"><h3>${esc(i.question)}</h3>
    <p class="sub">${esc(i.id)} &middot; approved by ${esc(i.approved_by)} &middot; ${esc(i.created_at)}</p>
    <div class="draftbox">${esc(i.answer)}</div></div>`).join('')
    : '<p class="empty">Empty. Approve a draft in the reviewer console and it appears here.</p>';
}
$('#repoload').onclick = loadRepo;

async function loadSources(){
  const d = await api('/api/sources');
  $('#srcout').innerHTML = `<div class="kpi">
    <div><b>${d.stats.documents}</b><span>approved documents</span></div>
    <div><b>${d.stats.passages}</b><span>indexed passages</span></div>
    <div><b>${d.stats.total_queries}</b><span>queries handled</span></div>
    <div><b>${d.stats.auto_answered}</b><span>auto-answered</span></div>
    <div><b>${d.stats.pending_review}</b><span>awaiting review</span></div>
    <div><b>${d.stats.repository_entries}</b><span>reusable answers</span></div>
  </div>
  <table><tr><th>Title</th><th>Product</th><th>Type</th><th>Published</th><th>Passages</th><th>Access</th></tr>
  ${d.items.map(s=>`<tr><td><a href="${s.url}" target="_blank" rel="noopener">${esc(s.title)}</a></td>
   <td>${esc(s.product_number)}</td><td>${esc(s.doc_type)}</td><td>${esc(s.published)}</td>
   <td>${s.passages}</td><td>${s.internal_only?'Internal only':'Public'}</td></tr>`).join('')}</table>`;
}

async function loadAudit(){
  const d = await api('/api/audit');
  $('#auout').innerHTML = d.items.length ? `<table><tr><th>Time</th><th>Actor</th><th>Action</th><th>Detail</th></tr>
   ${d.items.map(a=>`<tr><td>${esc(a.at)}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td>${esc(a.detail)}</td></tr>`).join('')}</table>`
   : '<p class="empty">No activity yet.</p>';
}
</script></body></html>
"""


# ---------------------------------------------------------------------------
# 9. HTTP SERVER  (stdlib only - swap for FastAPI later, routes are the same)
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "StatsSA-MVP/1.0"

    def log_message(self, fmt, *args):  # quieter console
        print(f"  {self.command} {self.path}")

    # -- helpers -----------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def is_reviewer(self) -> bool:
        return self.headers.get("X-API-Key") == REVIEWER_API_KEY

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/":
            return self._send(200, FRONTEND.encode("utf-8"), "text/html; charset=utf-8")

        if path == "/api/sources":
            return self.json({"items": source_list(), "stats": stats()})

        if path == "/api/repository":
            return self.json({"items": repository_list()})

        if path == "/api/audit":
            return self.json({"items": audit_list()})

        if path == "/api/reviews":
            if not self.is_reviewer():
                return self.json({"error": "Reviewer access required. Check the API key."}, 403)
            return self.json({"items": list_reviews()})

        if path == "/api/health":
            return self.json({"ok": True, "stats": stats()})

        return self.json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        data = self.body()

        if path == "/api/query":
            channel = data.get("channel", "public")
            if channel not in ("public", "media"):
                return self.json({"error": "channel must be 'public' or 'media'"}, 400)
            return self.json(handle_query(
                data.get("question", ""), channel, data.get("requester", "")
            ))

        m = re.match(r"^/api/reviews/([A-Za-z0-9\-]+)/(approve|reject)$", path)
        if m:
            if not self.is_reviewer():
                return self.json({"error": "Reviewer access required."}, 403)
            qid, action = m.group(1), m.group(2)
            reviewer = data.get("reviewer") or "unnamed reviewer"
            text = data.get("text", "")
            if action == "approve":
                return self.json(approve(qid, text, reviewer))
            return self.json(reject(qid, text, reviewer))

        return self.json({"error": "Not found"}, 404)


def main() -> None:
    init_db()
    audit("system", "startup", f"{len(SEED_DOCUMENTS)} documents, {len(INDEX.entries)} passages")

    print("=" * 70)
    print(" Stats SA AI assistant - MVP")
    print("=" * 70)
    print(f" Knowledge base : {len(SEED_DOCUMENTS)} approved documents, "
          f"{len(INDEX.entries)} indexed passages")
    print(f" Database       : {DB_PATH}")
    print(f" Reviewer key   : {REVIEWER_API_KEY}")
    print(f" Open           : http://{HOST}:{PORT}")
    print("=" * 70)
    print(" Press Ctrl+C to stop.\n")

    # Skip the auto-open on headless machines: set NO_BROWSER=1
    if not os.environ.get("NO_BROWSER"):
        try:
            webbrowser.open(f"http://{HOST}:{PORT}")
        except Exception:
            pass

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n Stopped.")
        server.server_close()


if __name__ == "__main__":
    main()


# =============================================================================
# NEXT STEPS - turning this MVP into the real thing
# =============================================================================
#
# 1. INGESTION (replace SEED_DOCUMENTS)
#    Write a separate ingest.py that downloads the PDF releases from
#    statssa.gov.za, extracts text per section/table, chunks it into passages,
#    and stores document metadata (product number, reference period, URL,
#    supersedes/superseded-by). Keep a scheduled re-run tied to the advance
#    release calendar so revised figures replace stale ones.
#    Note: statssa.gov.za blocks automated scraping, so agree a data-sharing
#    route with Stats SA rather than crawling the site.
#
# 2. RETRIEVAL
#    Swap PassageIndex for a hybrid store: BM25 (OpenSearch) + embeddings
#    (PostgreSQL + pgvector). Keep the same search() signature.
#
# 3. GENERATION
#    Add an open-weight model behind compose_answer(). Hard rule: it receives
#    only the retrieved passages and may not add facts. Keep citations
#    attached per sentence, and keep the extractive path as a fallback.
#
# 4. AUTH
#    Replace REVIEWER_API_KEY with OIDC (Keycloak) and map groups to the
#    roles: public, media_desk, reviewer, knowledge_admin.
#
# 5. FRAMEWORK
#    The route table maps one-to-one onto FastAPI if you want OpenAPI docs,
#    async and validation. The pipeline functions above need no changes.
# =============================================================================
