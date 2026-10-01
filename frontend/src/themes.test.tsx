import { describe, expect, it } from 'vitest'
import { pickOpenTextColumn } from './Themes'
import type { ColumnProfile } from './api'

// Pure helper only - Themes.tsx's own stateful default export has no test of its own, matching this
// repo's existing precedent for data-fetching wrapper components (see projects.test.tsx's own comment).

function col(overrides: Partial<ColumnProfile> = {}): ColumnProfile {
  return {
    name: 'col',
    position: 0,
    kind: 'open_text',
    confidence: 0.9,
    reason: '',
    unit: null,
    distinct: 1,
    missing: 0,
    median_words: 10,
    samples: [],
    sensitive: false,
    sensitive_reason: null,
    is_question: false,
    ...overrides,
  }
}

describe('pickOpenTextColumn', () => {
  it('returns null when no column is open_text', () => {
    const profile = { row_count: 100, columns: [col({ name: 'a', kind: 'segment' })] }
    expect(pickOpenTextColumn(profile)).toBeNull()
  })

  it('picks the single open_text candidate when there is only one', () => {
    const profile = { row_count: 100, columns: [col({ name: 'reviews.text' })] }
    expect(pickOpenTextColumn(profile)).toBe('reviews.text')
  })

  it('prefers the mostly-unique real free-text column over a repeated-per-row metadata column that also guessed open_text - the exact real bug (dimension/categories: a handful of distinct values repeated across thousands of rows, confirmed live on a real dataset)', () => {
    const profile = {
      row_count: 1597,
      columns: [
        // "dimension" appears FIRST in upload order (the old bug: first-in-order always won) but is
        // 1 distinct value repeated across every answered row - exactly the real "Dimensions in inches
        // 100.0%, 1 theme, no sub-themes" bug.
        col({ name: 'dimension', position: 0, distinct: 1, missing: 1032 }),
        col({ name: 'reviews.text', position: 1, distinct: 1580, missing: 0 }),
      ],
    }
    expect(pickOpenTextColumn(profile)).toBe('reviews.text')
  })

  it('respects a confirmed kind override, including switching AWAY from a column that was auto-guessed open_text', () => {
    const profile = {
      row_count: 100,
      columns: [col({ name: 'categories', distinct: 19 }), col({ name: 'reviews.text', position: 1, distinct: 95 })],
      confirmed: { columns: { categories: { kind: 'segment' as const, off: false } }, question: null },
    }
    expect(pickOpenTextColumn(profile)).toBe('reviews.text')
  })

  it('skips a column switched off even though its guessed/confirmed kind is still open_text', () => {
    const profile = {
      row_count: 100,
      columns: [col({ name: 'dimension', distinct: 1 }), col({ name: 'reviews.text', position: 1, distinct: 95 })],
      confirmed: { columns: { dimension: { kind: 'open_text' as const, off: true } }, question: null },
    }
    expect(pickOpenTextColumn(profile)).toBe('reviews.text')
  })

  it('prefers the longer-answer column between two that both clearly clear the uniqueness floor - the real dataset case where reviews.title (short, varied phrases) scored a HIGHER raw uniqueness ratio than reviews.text (longer, but reuses more boilerplate), even though reviews.text is the richer column worth analysing', () => {
    const profile = {
      row_count: 1597,
      columns: [
        col({ name: 'reviews.title', position: 0, distinct: 1270, missing: 17, median_words: 4 }),
        col({ name: 'reviews.text', position: 1, distinct: 1048, missing: 0, median_words: 24 }),
      ],
    }
    expect(pickOpenTextColumn(profile)).toBe('reviews.text')
  })

  it('falls back to the most unique candidate when NONE clear the uniqueness floor, rather than picking blind', () => {
    const profile = {
      row_count: 1000,
      columns: [
        col({ name: 'name', distinct: 60, median_words: 8 }), // uniqueness 0.06
        col({ name: 'prices', position: 1, distinct: 90, median_words: 2 }), // uniqueness 0.09, more unique but fewer words
      ],
    }
    expect(pickOpenTextColumn(profile)).toBe('prices')
  })
})
