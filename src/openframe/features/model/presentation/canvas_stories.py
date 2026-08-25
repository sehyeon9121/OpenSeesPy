"""Story (building floor level) CRUD for StaticsDrawingCanvas - Story
Manager's own state.

A ``Story`` never owns geometry; it is a thin, renamable label attached to
an elevation, and ``nodes_at_story`` re-derives which nodes belong to it by
Z-proximity every time it is asked, rather than storing a node-tag list that
could drift out of sync as the model is edited. ``rigid_diaphragm`` is the
only field that changes analysis behaviour - see
``canvas_model_build.py``'s ``_build_rigid_diaphragms`` and
``core.domain.model.RigidDiaphragm``.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from openframe.core.domain import Story

#: Nodes within this many model-length-units of a story's elevation count as
#: "at" that story - forgiving enough for the small floating-point noise a
#: hand-drawn or generated grid can pick up, tight enough that two real
#: floors a normal building's story height apart are never confused.
_STORY_Z_TOLERANCE = 1.0e-6


class _StoryMixin:
    def add_story(
        self, name: str, elevation: float, rigid_diaphragm: bool = False
    ) -> str | None:
        """Returns the new story's id, or ``None`` if ``name`` is already
        taken - mirrors ``add_load_case``'s own no-silent-overwrite rule."""
        if not name or name in self.stories:
            return None
        self._record_history()
        self.stories[name] = Story(id=name, name=name, elevation=elevation, rigid_diaphragm=rigid_diaphragm)
        self.story_state_changed.emit()
        return name

    def update_story(
        self,
        story_id: str,
        *,
        name: str | None = None,
        elevation: float | None = None,
        rigid_diaphragm: bool | None = None,
    ) -> bool:
        """Renaming changes the story's id too, same as ``rename_load_case``
        - nothing else references a Story by id (``nodes_at_story`` only
        ever looks it up by elevation), so no cascade is needed."""
        story = self.stories.get(story_id)
        if story is None:
            return False
        new_id = name if name is not None else story_id
        if new_id != story_id and new_id in self.stories:
            return False
        self._record_history()
        del self.stories[story_id]
        self.stories[new_id] = Story(
            id=new_id,
            name=new_id,
            elevation=story.elevation if elevation is None else elevation,
            rigid_diaphragm=story.rigid_diaphragm if rigid_diaphragm is None else rigid_diaphragm,
        )
        self.story_state_changed.emit()
        return True

    def delete_story(self, story_id: str) -> None:
        if story_id not in self.stories:
            return
        self._record_history()
        del self.stories[story_id]
        self.story_state_changed.emit()

    def nodes_at_story(self, story_id: str) -> tuple[int, ...]:
        story = self.stories.get(story_id)
        if story is None:
            return ()
        return tuple(
            sorted(
                tag
                for tag, node in self.nodes.items()
                if abs(node.z - story.elevation) <= _STORY_Z_TOLERANCE
            )
        )

    def auto_detect_stories(self) -> list[str]:
        """Group every drawn node by its Z coordinate and create one Story
        per elevation not already covered by an existing one - MIDAS' own
        "auto-detect stories" convenience. Named by Korean building
        convention: sequential "N층" at or above grade (Z >= 0), "N지하층"
        below it, counted separately from grade outward in each direction so
        a basement's numbering does not depend on how many stories are above
        it. Returns the newly created story ids (empty if every elevation
        already has one, or this is a 2D model - stories are a 3D/building
        concept)."""
        if self.ndm != 3 or not self.nodes:
            return []
        existing = [story.elevation for story in self.stories.values()]

        def _covered(z: float) -> bool:
            return any(abs(z - elevation) <= _STORY_Z_TOLERANCE for elevation in existing)

        candidates = sorted({node.z for node in self.nodes.values() if not _covered(node.z)})
        if not candidates:
            return []
        self._record_history()
        created: list[str] = []
        above = [z for z in candidates if z >= 0.0]
        below = sorted((z for z in candidates if z < 0.0), reverse=True)
        for index, elevation in enumerate(above, start=1):
            name = f"{index}층"
            if name in self.stories:
                continue
            self.stories[name] = Story(id=name, name=name, elevation=elevation)
            created.append(name)
        for index, elevation in enumerate(below, start=1):
            name = f"지하{index}층"
            if name in self.stories:
                continue
            self.stories[name] = Story(id=name, name=name, elevation=elevation)
            created.append(name)
        self.story_state_changed.emit()
        return created
