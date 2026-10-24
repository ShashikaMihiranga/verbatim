"""Cheap per-finding chart views; never change the shared report or the saved finding numbers."""
from dataclasses import replace

from .chart_data import ReportData, ThemeNode, ToneSplit, TrendSeries


STRUCTURED_KINDS = {'segment_skew', 'score_correlation', 'trend_shift'}


def reveal_folded_theme(data: ReportData, node: ThemeNode) -> ReportData:
    """A finding about the 8th+ theme must not highlight the same merged Other as every other finding.

    Show its real stored tone against the rest of the answers. The overview's seven-theme cap stays
    intact. Subtract weighted totals, not percentages, to avoid double-counting the promoted theme.
    """
    count = sum(t.count for t in data.themes) - node.count
    rest = replace(node, name='All other answers', color='other', theme_id=None, children=[],
                   count=count, share=round(count / data.answered * 100, 1) if data.answered else 0,
                   answer_refs=[], map_xy=None, callout=None, note='',
                   sentiment=(sum(t.count * t.sentiment for t in data.themes) - node.count * node.sentiment) / count if count else 0,
                   tones=ToneSplit(*(max(0, sum(t.count * t.tones[i] for t in data.themes)
                                            - node.count * node.tones[i]) / count if count else 0
                                     for i in range(3))))
    return replace(data, themes=[node, rest], selected_theme=node.name, hover_theme=node.name)


def focus_finding(data: ReportData, kind: str, theme: str, group: str = '',
                  chart_id: str = '') -> ReportData | None:
    """Keep original denominators. None means this finding has no evidence in the current view.

    Do not renormalize a selected theme to 100% or silently substitute the first available theme.
    Score/stacked-time charts retain an explicit complement so their bars still sum to 100%.
    """
    if kind not in STRUCTURED_KINDS:
        return data
    node = next((t for t in data.themes if t.name == theme and t.count > 0), None)
    if node is None:
        return None
    focused = replace(data, selected_theme=theme, hover_theme=theme)
    if kind == 'segment_skew':
        row = next((r for r in data.segment.rows if r.theme == theme), None)
        groups = data.segment.groups
        if row is None or not groups or len(row.values) != len(groups):
            return None
        gi = next((i for i, g in enumerate(groups) if g.label == group), None)
        if group and gi is None:
            return None
        tip = (f'{theme}: {row.values[gi]:g}% in {groups[gi].label}; '
               f'{row.overall:g}% overall.') if gi is not None else ''
        return replace(focused, segment=replace(data.segment, rows=[row],
                       highlight=(0, gi) if gi is not None else None, highlight_text=tip))
    if kind == 'score_correlation':
        index = data.themes.index(node)
        bands = data.score.bands
        if len(bands) < 2 or any(len(b.mix) != len(data.themes) for b in bands):
            return None
        others = [t for t in data.themes if t is not node]
        count = sum(t.count for t in others)
        # Real aggregate metadata, even though byScore only uses this node's label and colour.
        rest = replace(node, name='All other answers', color='other', theme_id=None,
                       count=count, share=sum(t.share for t in others), children=[], answer_refs=[],
                       sentiment=sum(t.count * t.sentiment for t in others) / count if count else 0,
                       tones=ToneSplit(*(sum(t.count * t.tones[i] for t in others) / count
                                         if count else 0 for i in range(3))))
        return replace(focused, themes=[node, rest], score=replace(data.score, bands=[
            replace(b, mix=[b.mix[index], round(100 - b.mix[index], 6)]) for b in bands
        ]))
    series = next((s for s in data.trend.series if s.theme == theme), None)
    if series is None or len(data.trend.labels) < 2 or len(series.values) != len(data.trend.labels):
        return None
    lines = [series]
    if chart_id == 'themeMixOverTime':
        lines.append(TrendSeries('All other answers', 'other', [round(100 - v, 6) for v in series.values]))
    return replace(focused, trend=replace(data.trend, series=lines))
