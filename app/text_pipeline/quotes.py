"""Representative verbatim quotes for the `quotes` report block (docs/DECISIONS.md, 2026-10-24 chart-block
stream). Pure code, no network - reuses `sentiment.py`'s lexicon scorer for each quote's `tone`, same
"cheap steps do the bulk" discipline every other text-pipeline module here follows.

The report already has a full verbatim drill-down ("See answers", `app/api_themes.py::theme_answers`) -
this is a different, smaller thing: a handful of REPRESENTATIVE quotes for the report's own narrative
blocks, picked automatically rather than browsed.
"""
from __future__ import annotations

import statistics

from ..chart_data import Quote, QuoteData
from ..cleaning.redact import redact_text
from .sentiment import score_text

MAX_THEMES = 4
MAX_PER_THEME = 2

# score_text returns the short "neg"/"neu"/"pos" codes (sentiment.py's own Literal type), but Quote.tone
# (app/chart_data.py) and f_quotes' own SC colour lookup (app/charts.py) both expect the full word -
# caught by this module's own tests before it shipped, not a silent mismatch.
_TONE_WORD = {"neg": "negative", "neu": "neutral", "pos": "positive"}


def build_quote_data(theme_texts: list[tuple[str, list[str]]]) -> QuoteData | None:
    """`theme_texts`: ordered (theme_name, real answer texts) pairs - the caller's job to order
    largest-theme-first and to exclude the merged "Other" bucket (a quote attributed to "Other" would be
    misleading: it is a mix of unrelated small themes, not one real idea - same reasoning
    `app/api_report.py`'s sentsun "Other" fallback already documents for a different block).

    Picks each theme's MOST TYPICAL answer(s) - closest to that theme's own median word count, not the
    shortest or longest outlier - matching `f_quotes`'s own default "Most typical" view
    (`app/charts.py`'s segmented control). Returns `None` when nothing real exists, the same "a valid
    empty result, not an error" contract every other `build_*_data` function in this app already follows.
    """
    quotes: list[Quote] = []
    for name, texts in theme_texts[:MAX_THEMES]:
        real = [t for t in texts if isinstance(t, str) and t.strip()]
        if not real:
            continue
        median_len = statistics.median(len(t.split()) for t in real)
        ranked = sorted(real, key=lambda t: abs(len(t.split()) - median_len))
        for text in ranked[:MAX_PER_THEME]:
            _, tone = score_text(text)
            quotes.append(Quote(text=redact_text(text)[0], theme=name, tone=_TONE_WORD[tone]))
    if not quotes:
        return None
    return QuoteData(quotes=quotes, highlight_index=0)
