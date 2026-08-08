import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.direct_model_workspace import DirectModelWorkspace
from openframe.core.domain.materials import MaterialFamily, ShearModulusMode


def test_material_page_separates_empty_kds_catalog_and_user_materials() -> None:
    application = QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()
    workspace.set_current_step("materials")
    page = workspace.materials_page

    assert application is QApplication.instance()
    assert workspace.stage_stack.currentWidget() is page
    assert page.kds_record_count.text() == "등록 레코드 0개"
    assert len(page.library.user_materials()) == 1
    assert page.current_material() is not None

    page.elastic_modulus_input.setValue(205_000.0)
    page.name_input.setText("사용자 강재")
    page.save_button.click()

    assert page.current_material().name == "사용자 강재"
    assert page.validation_message.text() == "저장됨"


def test_shear_deformation_controls_build_project_settings() -> None:
    application = QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()
    page = workspace.materials_page

    assert application is QApplication.instance()
    page.shear_enabled.setChecked(True)
    page.shear_mode.setCurrentIndex(page.shear_mode.findData(ShearModulusMode.USER_DEFINED))
    page.shear_modulus_input.setValue(78_000.0)

    settings = page.shear_settings()
    assert settings.enabled
    assert settings.modulus_mode == ShearModulusMode.USER_DEFINED
    assert settings.user_shear_modulus == 78_000.0
    assert settings.validate() == []


def test_setup_units_propagate_to_user_material_fields() -> None:
    application = QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()

    assert application is QApplication.instance()
    workspace.setup_page.force_unit.setCurrentText("N")
    workspace.setup_page.length_unit.setCurrentText("mm")

    page = workspace.materials_page
    assert page.elastic_modulus_unit.text() == "N/mm²"
    assert page.shear_modulus_unit.text() == "N/mm²"
    assert page.yield_strength_unit.text() == "N/mm²"
    assert page.density_unit.text() == "N/mm³"


def test_kds_material_family_selects_a_matching_database_kind() -> None:
    application = QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()
    page = workspace.materials_page

    assert application is QApplication.instance()
    page.kds_family.setCurrentIndex(page.kds_family.findData(MaterialFamily.CONCRETE))

    assert page.kds_database.currentData() == "kds_concrete"
    assert page.kds_database.currentText() == "KDS 콘크리트 재료 DB"
