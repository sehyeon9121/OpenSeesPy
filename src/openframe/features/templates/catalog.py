"""Reads the bundled template manifest (``resources/templates/manifest.json``).

Each template is an ordinary ``.ofsm`` project file, generated once through
the real canvas API (see the repo's template-generation notes) rather than
hand-written JSON, so it opens through the exact same
``DirectModelWorkspace.open_project_file`` path a user-saved project does -
no separate "template loader" to keep in sync with the project-file format.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Same "plain Path(__file__)" convention app_header.py's APP_ICON_PATH uses
#: for resources/icons - this package is always installed as regular files
#: (never a zipped egg), so there is no need for importlib.resources here.
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "resources" / "templates"
_MANIFEST_PATH = TEMPLATES_DIR / "manifest.json"


@dataclass(frozen=True, slots=True)
class TemplateEntry:
    id: str
    title: str
    subtitle: str
    description: str
    tags: tuple[str, ...]
    hint: str
    path: Path
    #: None for a plain canvas template (the first 3: 캔버스에 바로 열림). Set
    #: to an ``AnalysisKind`` value (e.g. "buckling") for a template that
    #: needs a solver the canvas's own MaterialFreeStaticsSolver cannot run -
    #: opening one instead goes through the same "정밀해석으로 내보내기"
    #: script-export/import pipeline a hand-drawn model uses, landing on
    #: SETUP with ``analysis_options`` already applied to the matching kind's
    #: settings card - see MainWindow._open_template.
    analysis_kind: str | None = None
    analysis_options: dict[str, float | int | str | bool] = field(default_factory=dict)


def load_template_catalog() -> list[TemplateEntry]:
    """All bundled templates, in manifest order. Returns an empty list
    (rather than raising) if the manifest is missing - a packaging mistake
    should make the Templates gallery show "no templates" instead of
    crashing the whole app on startup."""
    if not _MANIFEST_PATH.exists():
        return []
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = []
    for item in data.get("templates", []):
        analysis = item.get("analysis") or {}
        entries.append(
            TemplateEntry(
                id=item["id"],
                title=item["title"],
                subtitle=item.get("subtitle", ""),
                description=item.get("description", ""),
                tags=tuple(item.get("tags", ())),
                hint=item.get("hint", ""),
                path=TEMPLATES_DIR / item["file"],
                analysis_kind=analysis.get("kind"),
                analysis_options=dict(analysis.get("options", {})),
            )
        )
    return entries
