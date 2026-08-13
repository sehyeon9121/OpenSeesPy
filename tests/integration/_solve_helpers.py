"""Shared helper for tests that trigger ModelingInterfacePage.solve().

solve() runs MaterialFreeStaticsSolver in a background QThread (so the GUI
stays responsive and can show a running-analysis dialog) instead of blocking
synchronously, so a test cannot just call it and immediately assert on
page.results - the completed/finished signals are delivered via a queued
connection that only runs once the event loop gets a turn.
"""

from PySide6.QtWidgets import QApplication


def solve_and_wait(page) -> None:
    page.solve()
    thread = page._solve_thread
    if thread is not None:
        thread.wait()
    for _ in range(5):
        QApplication.processEvents()
