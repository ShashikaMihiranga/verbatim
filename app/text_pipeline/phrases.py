"""Recurring-phrase extraction for the `top_phrases` report block (docs/DECISIONS.md, 2026-10-24
chart-block stream). Pure code, no network, no model calls - same "cheap steps do the bulk" discipline
`sentiment.py`'s own lexicon scorer already follows (SPEC.md section 2), reusing that exact tokenizer and
scorer rather than inventing a second one.

Counts a phrase ONCE per answer it appears in (not once per raw occurrence), so one respondent repeating
themselves within a single answer cannot dominate the ranking the way raw n-gram frequency would. Each
surviving phrase's `sentiment` is the average lexicon score of the FULL ANSWERS it appears in (not of the
2-4 word phrase alone, which is too short for the lexicon's negation/intensifier window logic to read
reliably) - matches `Phrase.sentiment`'s own documented meaning in app/chart_data.py: "average sentiment
of answers containing it."
"""
from __future__ import annotations

from collections import defaultdict

from ..chart_data import Phrase, PhraseData
from .sentiment import _tokenize, score_text

# A short, hand-curated list in the same spirit as the lexicon itself (sentiment.py's own docstring:
# "Lexicon in code") - common English function words that make a phrase read as noise rather than a real
# recurring idea ("of the", "to be", "and it"). Not exhaustive; good enough to keep the top phrases
# readable, the same bar the lexicon itself is held to. Deliberately NOT included: "not" - dropping it as
# a stopword would trim "not worth the price" into "worth the price", the opposite meaning (the same
# negation `sentiment.py`'s own `NEGATIONS` list exists to handle, for exactly this reason).
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at", "by", "for", "with", "about",
    "as", "is", "was", "are", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those",
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "do", "does", "did", "have", "has", "had", "so", "than", "then", "there", "here",
    "s", "t", "re", "ve", "ll", "d", "m",
    "am", "i'm", "i've", "i'd", "i'll", "it's", "that's", "there's", "you're", "we're", "they're",
})


def _phrase_tokens(text: str) -> list[str]:
    # The shared lexicon tokenizer keeps a bare "'" as a word (heights like 5'4"), which leaked into
    # phrase chips. Curly apostrophes ("I’m") are normalised inside _tokenize itself since BUG-033.
    return [w.strip("'") for w in _tokenize(text) if w.strip("'")]

MIN_PHRASE_WORDS, MAX_PHRASE_WORDS = 2, 4

# A phrase needs at least this many DISTINCT answers behind it to count as "recurring" at all - deliberately
# NOT `app.cleaning.suppression.min_group_size()`'s 30-answer floor (that floor is about a THEME's own
# reporting granularity; one phrase said by a handful of people is a much lower-stakes, looser signal, the
# same class as `FreqData.items`/the long_tail footnote, neither of which uses that floor either).
MIN_PHRASE_ANSWERS = 3

TOP_N = 10


def build_phrase_data(answer_texts: list[str]) -> PhraseData | None:
    """Real answer texts in, the report's `phrases` block data out - or `None` if nothing recurs often
    enough to be worth showing (same "a valid empty result, not an error" contract every other
    `build_*_data` function in this app already follows)."""
    phrase_answers: dict[str, list[str]] = defaultdict(list)
    for text in answer_texts:
        if not isinstance(text, str) or not text.strip():
            continue
        words = _phrase_tokens(text)
        seen_in_this_answer: set[str] = set()
        for n in range(MIN_PHRASE_WORDS, MAX_PHRASE_WORDS + 1):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                # Trim-only stopword filtering (standard phrase-extraction practice): a phrase with a
                # stopword at either EDGE ("of the dealer", "the dealer is") reads worse than one with a
                # stopword only in the middle ("not worth the price") - interior stopwords are kept, since
                # dropping them would turn real multi-word phrases into disconnected word pairs.
                if gram[0] in STOPWORDS or gram[-1] in STOPWORDS:
                    continue
                if all(w in STOPWORDS for w in gram):
                    continue
                phrase = " ".join(gram)
                if phrase not in seen_in_this_answer:
                    seen_in_this_answer.add(phrase)
                    phrase_answers[phrase].append(text)

    candidates = [(p, texts) for p, texts in phrase_answers.items() if len(texts) >= MIN_PHRASE_ANSWERS]
    if not candidates:
        return None
    # Longer phrases are a stronger, more specific signal than a shorter phrase with the same raw count
    # (e.g. "home charger" over "the charger") - ties within the same length favour the latest-seen for a
    # stable, deterministic order on equal input rather than relying on dict-iteration order.
    candidates.sort(key=lambda pt: (len(pt[1]), len(pt[0].split())), reverse=True)
    top = candidates[:TOP_N]

    phrases = []
    for text, texts in top:
        avg_sentiment = sum(score_text(t)[0] for t in texts) / len(texts)
        phrases.append(Phrase(text=text, count=len(texts), sentiment=round(avg_sentiment, 2)))
    # No highlight: in the gallery mockup it draws one chip as hovered (a dark ring), which on a real report
    # looks like a selection that means nothing and cannot be changed (BUG-069).
    return PhraseData(phrases=phrases, highlight="")
