"""Create shared services and launch the desktop application."""

import os
import sys


def run_desktop_app() -> int:
    # Force the OpenGL RHI backend for Qt Quick 3D. The Windows default (Direct3D11)
    # combined with QQuickWidget's texture blit + MSAA is a known Qt6 combination that
    # renders the View3D scene as garbled/rainbow noise on some GPU driver stacks
    # instead of the actual model - this must be set before any Qt module is imported.
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")

    # Qt imports stay at the application boundary so domain modules remain GUI-independent.
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from openframe.app.shell.app_header import APP_ICON_PATH
    from openframe.app.shell.main_window import MainWindow
    from openframe.app.shell.theme import apply_application_theme
    from openframe.core.domain import AnalysisKind
    from openframe.features.analysis.application.run_analysis import RunAnalysisService
    from openframe.features.analysis.linear_static.module import LinearStaticAnalysis
    from openframe.features.analysis.nonlinear_static.module import NonlinearStaticAnalysis
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
    run_analysis_service = RunAnalysisService(
        {
            AnalysisKind.LINEAR_STATIC: linear_static,
            AnalysisKind.NONLINEAR_STATIC: nonlinear_static,
        }
    )

    window = MainWindow(
        open_model_service=open_model_service,
        run_analysis_service=run_analysis_service,
    )
    window.show()
    return application.exec()
