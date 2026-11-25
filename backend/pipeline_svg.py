"""Escaped colour-coded SVG pipeline (C-17) plus a text mirror. State = icon AND word, never colour alone. No external assets."""
from __future__ import annotations
from html import escape
from .monitoring import nodes
COLORS = {"PENDING": ("--dr-muted", "#6b7280"), "IN_PROGRESS": ("--dr-info", "#2563eb"), "AWAITING_APPROVAL": ("--dr-warn", "#b45309"),
          "ROLLBACK_AWAITING": ("--dr-warn", "#b45309"), "TOKEN_EXPIRED": ("--dr-danger", "#b91c1c"), "COMPLETED": ("--dr-ok", "#15803d"),
          "FAILED": ("--dr-danger", "#b91c1c"), "ROLLED_BACK": ("--dr-info", "#2563eb"), "BLOCKED": ("--dr-muted", "#6b7280")}
ICON_PATHS = {"circle": '<circle cx="12" cy="12" r="9"/>', "play": '<circle cx="12" cy="12" r="9"/><path d="m10 8 5 4-5 4z"/>',
              "hourglass": '<path d="M6 3h12M6 21h12M7 3v4l5 5-5 5v4M17 3v4l-5 5 5 5v4"/>', "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
              "circle-check": '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>', "circle-x": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
              "rotate-ccw": '<path d="M4 12a8 8 0 1 0 3-6.2L4 8"/><path d="M4 3v5h5"/>', "ban": '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>'}
def _e(v) -> str: return escape(str(v), quote=True)
def _col(st): v, f = COLORS[st]; return f"var({v},{f})"
def _icon(name, x, y, color, size=18):
    return (f'<g transform="translate({x},{y}) scale({size / 24})" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICON_PATHS[name]}</g>')
def pipeline_text(s: dict) -> list[str]:
    return [f"{n['index']:02d} {n['label']}: {n['status_label']}" for n in nodes(s)]
def pipeline_svg(s: dict, audit_count: int | None = None) -> str:
    gate = s["phase"] == "WAITING_APPROVAL"; last = (s.get("last_result") or {}).get("step")
    actors = [("Coordinator", "Explains next step", "#7c3aed"), ("HITL Gate", "Awaiting approval" if gate else "Closed", "#b45309"),
              ("Failover Operator", f"Last: {last[:7]}" if last else "Idle", "#d97706"),
              ("Audit Chain", f"{audit_count} events" if audit_count is not None else "Hash-chained", "#0e7490")]
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 660 250" width="100%" role="img" aria-label="Drill pipeline: coordinator, approval gate, '
         'failover operator, audit chain and six runbook steps" font-family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif"><title>DR drill pipeline</title>']
    for i, (name, sub, color) in enumerate(actors):
        x = 8 + i * 162; active = name == "HITL Gate" and gate
        p.append(f'<rect x="{x}" y="8" width="150" height="58" rx="10" fill="{"var(--dr-warn-bg,#fbe3b0)" if active else "var(--dr-card,#fff)"}" stroke="{color}" stroke-width="2"/>'
                 f'<text x="{x + 10}" y="30" font-size="13" font-weight="600" fill="var(--dr-text,#0b0b0b)">{_e(name)}</text>'
                 f'<text x="{x + 10}" y="50" font-size="11" fill="var(--dr-muted,#6b7280)">{_e(sub)}</text>')
        if i < 3: p.append(f'<path d="M{x + 150} 37h12" stroke="var(--dr-muted,#6b7280)" stroke-width="2"/>')
    for n in nodes(s):
        x = 8 + (n["index"] - 1) * 108; c = _col(n["status"])
        p.append(f'<rect x="{x}" y="100" width="100" height="120" rx="10" fill="var(--dr-card,#fff)" stroke="{c}" stroke-width="2"/>'
                 + _icon(n["icon"], x + 8, 108, c, 20)
                 + f'<text x="{x + 34}" y="123" font-size="12" font-weight="600" fill="var(--dr-text,#0b0b0b)">{n["index"]:02d}</text>'
                 f'<text x="{x + 8}" y="158" font-size="11" fill="var(--dr-text,#0b0b0b)">{_e(n["label"][:15])}</text>'
                 f'<text x="{x + 8}" y="176" font-size="11" fill="var(--dr-text,#0b0b0b)">{_e(n["label"][15:30].strip())}</text>'
                 f'<text x="{x + 8}" y="206" font-size="11" font-weight="600" fill="{c}">{_e(n["status_label"][:16])}</text>')
    p.append("</svg>"); return "".join(p)
