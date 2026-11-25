"""LocalMarkdownRetriever: the only reader of data/*.md."""
from __future__ import annotations
import re
from pathlib import Path
DATA = Path(__file__).resolve().parent.parent / "data"
def _sections(path: Path) -> dict[str, str]:
    out, key = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            key = line[3:].strip(); out[key] = ""
        elif key:
            out[key] += line + "\n"
    return {k: v.strip() for k, v in out.items()}
class LocalMarkdownRetriever:
    def __init__(self, data_dir: Path | str = DATA):
        self.runbook = _sections(Path(data_dir) / "dr_runbook.md")
        self.templates = _sections(Path(data_dir) / "comms_templates.md")
    def get_step(self, step_id: str) -> str:
        return self.runbook.get(step_id, "")
    def get_template(self, letter: str) -> str:
        for k, v in self.templates.items():
            if re.match(rf"Template {re.escape(letter.upper())}\b", k):
                return v
        return ""
