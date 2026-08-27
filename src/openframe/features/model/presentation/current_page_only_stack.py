"""``_CurrentPageOnlyStack`` - extracted out of ``modeling_interface_page.py``
so other pages (e.g. ``analysis_settings_sidebar.py``) can reuse the exact
same "size hint comes from the current page only" stack instead of each
inventing their own. See the class's own docstring for why the plain
``QStackedWidget`` behaviour (sizeHint = max over every page, even hidden
ones) is wrong for a narrow, fixed-width side panel.
"""

from PySide6.QtWidgets import QStackedWidget


class _CurrentPageOnlyStack(QStackedWidget):
    """A ``QStackedWidget`` whose size hint comes only from the page actually
    showing, not the widest of all seven — the plain version reports
    ``max(sizeHint() for every page)`` even though six of them are hidden,
    so the 300px-wide category editor column (``_build_2d_editor_panel``)
    had to make room for whichever category page happened to be widest
    (부재's 단면 미리보기 + form, in practice) no matter which one was
    actually open, forcing a horizontal scrollbar even on the narrow 노드
    분할 page. Switching pages needs an explicit ``updateGeometry()`` since
    Qt does not know a widget's size hint changed on its own.
    """

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()

    def hasHeightForWidth(self) -> bool:
        # Deliberately always False, even though the current page's own
        # hasHeightForWidth() (from its word-wrapped QLabels - 노드 추가/이동·
        # 복사/아치/부재 all have one) would say True. sizeHint() above already
        # gives the parent layout a perfectly good static height for
        # whichever page is current, computed at that page's own natural
        # width. Letting hasHeightForWidth()/heightForWidth() propagate up
        # instead put the outer QVBoxLayout (_build_editor_scroll's ``root``)
        # into Qt's dynamic heightForWidth codepath for this item, which
        # computed a wildly inflated height (~1000px panels for ~450px of
        # actual content) and then centered this stack inside that oversized
        # cell - the fields visibly sank toward the middle of the panel
        # instead of staying pinned at the top. Reporting a plain, static
        # size (no heightForWidth) avoids that codepath entirely.
        return False
