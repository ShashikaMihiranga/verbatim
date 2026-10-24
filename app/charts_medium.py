"""Group-size × theme-mix geometry, distinct from the existing theme × tone Marimekko."""
from __future__ import annotations

import math

from .chart_data import ReportData


def group_mix_columns(data: ReportData) -> list[dict]:
    groups = data.segment.groups
    if not groups or not data.segment.rows:
        return []
    colors = {t.name: t.color for t in data.themes}
    columns = []
    for index, group in enumerate(groups):
        if group.n <= 0:
            return []
        entries = []
        for row in data.segment.rows:
            if index >= len(row.values):
                return []
            value = row.values[index]
            if not math.isfinite(value) or not 0 <= value <= 100:
                return []
            color = colors.get(row.theme, 'other')
            color = color if color in {f't{i}' for i in range(1, 8)} else 'other'
            if value > 0:
                entries.append((row.theme, value, color))
        shown = sum(value for _, value, _ in entries)
        if shown > 100 + len(data.segment.rows) * 0.11:
            return []
        remainder = round(max(0, 100 - shown), 1)
        if remainder > 0.1:
            entries.append(('Other / not shown', remainder, 'other'))
        if not entries:
            return []
        columns.append({'label': group.label, 'n': group.n, 'entries': entries})
    return columns


def f_group_mix(data: ReportData):
    from .charts import esc, fmt, hdr

    columns = group_mix_columns(data)
    if not columns:
        body = hdr('Group size and theme mix', 'No eligible grouped answers are available.')
        return f'<div style="padding:56px 48px">{body}</div>', 1180, 240
    total = sum(c['n'] for c in columns)
    body = hdr('Group size and theme mix',
               f'{data.segment.name}. Width is each shown group\'s share of {fmt(total)} answers; height is its theme mix.')
    cells, keys = [], []
    for index, col in enumerate(columns, 1):
        # A column's slight rounding drift is normalized for geometry only. Printed input percentages
        # stay unchanged; no respondent count is invented from a rounded percentage.
        entry_total = sum(v for _, v, _ in col['entries'])
        stack = ''.join(
            f'<div data-theme="{esc(name)}" title="{esc(name)}: {value:g}%" '
            f'style="height:{value / entry_total * 100:.4f}%;min-height:0;background:var(--{color});'
            f'border-bottom:2px solid var(--bg);box-sizing:border-box"></div>'
            for name, value, color in col['entries']
        )
        labels = ''.join(
            f'<div style="font-size:13px;line-height:1.5;margin-top:3px">'
            f'<span aria-hidden="true" style="display:inline-block;width:9px;height:9px;margin-right:6px;background:var(--{color})"></span>{esc(name)} '
            f'<strong>{value:g}%</strong></div>' for name, value, color in col['entries']
        )
        cells.append(
            f'<div style="flex:{col["n"]} 1 0;min-width:0">'
            f'<div style="height:360px;overflow:hidden">{stack}</div>'
            f'<div title="{esc(col["label"])}" style="font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:8px">{index}. {esc(col["label"])}</div></div>'
        )
        keys.append(
            f'<div><div style="font-size:15px;font-weight:600;overflow-wrap:anywhere">{index}. {esc(col["label"])}</div>'
            f'<div style="font-size:13px;color:var(--muted)">{fmt(col["n"])} answers · {col["n"] / total * 100:.1f}%</div>{labels}</div>'
        )
    note = ('Only surviving groups are shown. Percentages below each column name every colour; '
            'Other / not shown is the remainder outside the displayed theme rows.')
    html = (f'<div style="padding:56px 48px">{body}'
            f'<div style="display:flex;gap:4px;align-items:flex-start;margin-top:28px">{"".join(cells)}</div>'
            f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:24px;margin-top:28px">{"".join(keys)}</div>'
            f'<p style="color:var(--muted);font-size:14px;margin-top:24px">{note}</p></div>')
    max_entries = max(len(c['entries']) for c in columns)
    key_rows = math.ceil(len(columns) / 5)
    return html, 1180, 610 + key_rows * (70 + 24 * max_entries)
