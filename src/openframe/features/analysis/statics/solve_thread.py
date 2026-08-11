"""Background execution of MaterialFreeStaticsSolver so the GUI stays responsive.

Mirrors ``features/analysis/presentation/analysis_run_thread.py``'s pattern for
the OpenSeesPy-import solve path - same shape, so the 2D free-modeling page's
"해석 실행 중" dialog behaves identically to the one shown there.
"""

from PySide6.QtCore import QThread, Signal

from openframe.core.domain import AnalysisResult, AnalysisStatus, StructuralModel
from openframe.features.analysis.statics.modal_solver import ModalStaticsSolver
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver


class MaterialFreeSolveThread(QThread):
    completed = Signal(object)

    def __init__(self, solver: MaterialFreeStaticsSolver, model: StructuralModel) -> None:
        super().__init__()
        self._solver = solver
        self._model = model

    def run(self) -> None:
        try:
            result = self._solver.solve(self._model)
        except Exception as error:  # noqa: BLE001 - never crash the GUI event loop.
            result = AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"예상하지 못한 해석 오류: {error}"],
            )
        self.completed.emit(result)


class ModalSolveThread(QThread):
    completed = Signal(object)

    def __init__(
        self,
        solver: ModalStaticsSolver,
        model: StructuralModel,
        *,
        num_modes: int,
        length_unit: str,
    ) -> None:
        super().__init__()
        self._solver = solver
        self._model = model
        self._num_modes = num_modes
        self._length_unit = length_unit

    def run(self) -> None:
        try:
            result = self._solver.solve(
                self._model, num_modes=self._num_modes, length_unit=self._length_unit
            )
        except Exception as error:  # noqa: BLE001 - never crash the GUI event loop.
            result = AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"예상하지 못한 해석 오류: {error}"],
            )
        self.completed.emit(result)
