"""HTML fragments for the card UI. Every dynamic string goes through html.escape; no external JS, CDN or images."""
from __future__ import annotations
from html import escape
from .constants import (LABELS, PREREQUISITE, ROLLBACK_PLANS, STEP_OWNERS, TARGET_DURATIONS, TARGET_RESOURCES, TARGET_RTO_SECONDS, short_id)
from .guardrails import mask_token
from .monitoring import STATUS_META, display_status, format_mmss, step_row_detail
from .pipeline_svg import ICON_PATHS
def esc(v) -> str: return escape(str(v), quote=True)
def icon(name: str, size: int = 18) -> str:
    return (f'<svg class="dr-icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON_PATHS[name]}</svg>')
def title_row(title: str, pill: str) -> str:
    return f'<div class="dr-title-row"><span class="dr-title">{esc(title)}</span><span class="dr-pill">{esc(pill)}</span></div>'
def caption(scenario: str, drill_id: str | None) -> str:
    return f'<div class="dr-caption">Scenario: {esc(scenario)} · {"Drill " + esc(drill_id[:4]) if drill_id else "No drill started"}</div>'
def metrics(progress_pct: float, elapsed_rto) -> str:
    return ('<div class="dr-metrics"><div class="dr-metric"><div class="dr-metric-l">Progress</div>'
            f'<div class="dr-metric-v">{progress_pct:.0f}%</div></div><div class="dr-metric"><div class="dr-metric-l">Simulated RTO</div>'
            f'<div class="dr-metric-v">{esc(int(elapsed_rto))} / {TARGET_RTO_SECONDS}s</div></div></div>')
def pipeline_rows(s: dict | None, steps) -> str:
    rows = ['<div class="dr-card-title">Pipeline</div><div role="list">']
    for i, step in enumerate(steps, 1):
        status, detail = ("PENDING", "") if s is None else (display_status(s, step), step_row_detail(s, step))
        ic, label = STATUS_META[status]
        rows.append(f'<div class="dr-row dr-st-{esc(status.lower())}" role="listitem" aria-label="{i} {esc(LABELS[step])}: {esc(label)}">'
                    f'<span class="dr-ic">{icon(ic)}</span><span class="dr-lbl">{i}. {esc(LABELS[step])}</span><span class="dr-det">{esc(detail)}</span></div>')
    return "".join(rows) + "</div>"
def approval_card(s: dict, now: float | None = None) -> str:
    step, purpose, expired = s["pending_action"], s["gate_purpose"], s["gate_status"] == "EXPIRED"
    pre = PREREQUISITE.get(step)
    chips = (f'<span class="dr-chip-i">{icon("check", 14) if False else icon("circle-check", 14)} Prerequisite {esc(short_id(pre))} completed</span>' if pre
             else '<span class="dr-chip-i">No prerequisite</span>')
    return (f'<div class="dr-ap-title">{"Rollback" if purpose == "ROLLBACK" else "Approve"}: {esc(short_id(step))} {esc(LABELS[step])}</div>'
            f'<div class="dr-ap-owner">Owner: {esc(STEP_OWNERS[step])}<br>Target: {esc(TARGET_RESOURCES[step])} · target {TARGET_DURATIONS[step]} s<br>'
            f'Rollback plan: {esc(ROLLBACK_PLANS.get(step, "none"))}</div><div class="dr-ap-chips">{chips}</div>'
            f'<div class="dr-ap-owner">Token {esc(mask_token(s["approval_id"]))} · re-issues used {esc(s["reissue_count"])}</div>')
