"""Create shared services and launch the desktop application."""

import os
import sys


def run_desktop_app() -> int:
    # Force the OpenGL RHI backend for Qt Quick 3D. The Windows default (Direct3D11)
    # combined with QQuickWidget's texture blit + MSAA is a known Qt6 combination that
    # renders the View3D scene as garbled/rainbow noise on some GPU driver stacks
    # instead of the actual model - this must be set before any Qt module is imported.
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")

    # Windows treats an unmarked process as DPI-unaware by default, so on any
    # scaled display (125%/150%/...) it bitmap-stretches the whole window to
    # match the monitor's real DPI instead of letting Qt render at native
    # resolution - the exact "blurry, low-resolution-looking text" symptom
    # reported against a small (non-maximized) window. Must run before
    # QApplication exists; SetProcessDpiAwareness(2) is PROCESS_PER_MONITOR_
    # DPI_AWARE, falling back to the coarser SetProcessDPIAware() on older
    # Windows builds that lack shcore, and silently doing nothing on any
    # other OS (or if both calls are unavailable) rather than failing to launch.
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

    # Qt imports stay at the application boundary so domain modules remain GUI-independent.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    # Rounds a fractional scale factor (Windows' 125%/150%/175% presets) to
    # the nearest whole number only when actually drawing, rather than
    # snapping the *reported* factor first and rendering everything at that
    # coarser size - the other half of the same blurry-text fix as the DPI
    # awareness call above. Must also be set before QApplication exists.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    from openframe.app.shell.app_header import APP_ICON_PATH
    from openframe.app.shell.main_window import MainWindow
    from openframe.app.shell.theme import apply_application_theme
    from openframe.core.domain import AnalysisKind
    from openframe.features.analysis.application.run_analysis import RunAnalysisService
    from openframe.features.analysis.buckling.module import BucklingAnalysis
    from openframe.features.analysis.linear_static.module import LinearStaticAnalysis
    from openframe.features.analysis.modal.module import ModalAnalysis
    from openframe.features.analysis.nonlinear_static.module import NonlinearStaticAnalysis
    from openframe.features.analysis.response_spectrum.module import ResponseSpectrumAnalysis
    from openframe.features.analysis.time_history.module import TimeHistoryAnalysis
    from openframe.features.model.application.open_model import OpenModelService
    from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
    from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

    application = QApplication(sys.argv)
    application.setApplicationName("OpenFrame Studio")
    application.setOrganizationName("OpenFrame")
    if APP_ICON_PATH.exists():
        application.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    apply_application_theme(application)

    model_importer = OpenSeesModelImporter()
    open_model_service = OpenModelService(model_importer)

    analysis_runner = OpenSeesProcessRunner()
    linear_static = LinearStaticAnalysis(analysis_runner)
    nonlinear_static = NonlinearStaticAnalysis(analysis_runner)
    modal = ModalAnalysis(analysis_runner)
    time_history = TimeHistoryAnalysis(analysis_runner)
    buckling = BucklingAnalysis(analysis_runner)
    response_spectrum = ResponseSpectrumAnalysis(analysis_runner)
    run_analysis_service = RunAnalysisService(
        {
            AnalysisKind.LINEAR_STATIC: linear_static,
            AnalysisKind.NONLINEAR_STATIC: nonlinear_static,
            AnalysisKind.MODAL: modal,
            AnalysisKind.TIME_HISTORY: time_history,
            AnalysisKind.BUCKLING: buckling,
            AnalysisKind.RESPONSE_SPECTRUM: response_spectrum,
        }
    )

    window = MainWindow(
        open_model_service=open_model_service,
        run_analysis_service=run_analysis_service,
    )
    # Nothing persists window geometry between launches (see
    # imported_model_units.py for the app's only QSettings use, unrelated to
    # this), so every launch starts at whatever small default size Qt itself
    # picks - too small for the 3D workbench's own toolbars, which overlap
    # rather than wrap or scroll at that width. Starting maximized is what a
    # first-time user already has to do by hand to make that go away.
    window.showMaximized()
    return application.exec()
