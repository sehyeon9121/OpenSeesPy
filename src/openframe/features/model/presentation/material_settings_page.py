"""Clean material editor for models authored inside OpenFrame."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain.materials import (
    MaterialDefinition,
    MaterialFamily,
    ShearDeformationSettings,
    ShearModulusMode,
)
from openframe.core.domain.units import DEFAULT_UNIT_SYSTEM, UnitSystem
from openframe.features.model.application.material_library import MaterialLibrary
from openframe.infrastructure.materials.empty_kds_catalog import EmptyKdsMaterialCatalog

FAMILY_LABELS = {
    MaterialFamily.CONCRETE: "콘크리트",
    MaterialFamily.STRUCTURAL_STEEL: "구조용 강재",
    MaterialFamily.REINFORCING_STEEL: "철근",
    MaterialFamily.ELASTIC_ISOTROPIC: "등방성 탄성재료",
    MaterialFamily.OTHER: "기타",
}


class MaterialSettingsPage(QFrame):
    """Edits elastic material data; nonlinear behavior is intentionally untouched."""

    continue_requested = Signal()

    def __init__(
        self,
        library: MaterialLibrary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("materialSettingsPage")
        self.library = library or MaterialLibrary(EmptyKdsMaterialCatalog())
        self._selected_material_id: str | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.material_count = QLabel("재료 0")
        self.material_count.setObjectName("materialCountBadge")

        self.source_tabs = QTabWidget()
        self.source_tabs.setObjectName("materialSourceTabs")
        self.source_tabs.addTab(self._build_kds_page(), "KDS 재료 DB")
        self.source_tabs.addTab(self._build_user_page(), "프로젝트 재료")
        root.addWidget(self.source_tabs, 1)

        footer = QFrame()
        footer.setObjectName("materialFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 7, 14, 7)
        hint = QLabel("유효한 프로젝트 재료는 다음 단면 설정 단계에서 사용할 수 있습니다.")
        hint.setObjectName("materialFooterHint")
        footer_layout.addWidget(hint)
        footer_layout.addStretch(1)
        self.continue_button = QPushButton("단면 설정으로 계속  →")
        self.continue_button.setObjectName("materialContinueButton")
        self.continue_button.clicked.connect(self.continue_requested)
        footer_layout.addWidget(self.continue_button)
        root.addWidget(footer)

        self._create_material()

    def _build_kds_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("materialTabPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        browser = QFrame()
        browser.setObjectName("materialBrowserPanel")
        browser.setFixedWidth(260)
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(12, 12, 12, 12)
        browser_layout.setSpacing(8)
        heading = QLabel("KDS 재료 카탈로그")
        heading.setObjectName("materialPanelTitle")
        family_label = QLabel("재료 종류")
        family_label.setObjectName("materialFilterLabel")
        self.kds_family = QComboBox()
        self.kds_family.addItem("전체 재료", None)
        for family, label in FAMILY_LABELS.items():
            self.kds_family.addItem(label, family)
        database_label = QLabel("DB 종류")
        database_label.setObjectName("materialFilterLabel")
        self.kds_database = QComboBox()
        search_label = QLabel("검색")
        search_label.setObjectName("materialFilterLabel")
        self.kds_search = QLineEdit()
        self.kds_search.setPlaceholderText("재료명 또는 등급 검색…")
        self.kds_list = QListWidget()
        self.kds_list.setObjectName("kdsMaterialList")
        browser_layout.addWidget(heading)
        browser_layout.addWidget(family_label)
        browser_layout.addWidget(self.kds_family)
        browser_layout.addWidget(database_label)
        browser_layout.addWidget(self.kds_database)
        browser_layout.addWidget(search_label)
        browser_layout.addWidget(self.kds_search)
        browser_layout.addWidget(self.kds_list, 1)
        layout.addWidget(browser)

        detail = QFrame()
        detail.setObjectName("kdsEmptyPanel")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(40, 40, 40, 40)
        detail_layout.addStretch(1)
        title = QLabel("KDS 재료 데이터 대기 중")
        title.setObjectName("kdsEmptyTitle")
        description = QLabel(
            "검증된 설계기준 재료 데이터가 연결되면 재료명, 등급 및 기준 버전으로 "
            "검색할 수 있습니다. 현재는 데이터 공급자 구조만 연결되어 있습니다."
        )
        description.setObjectName("kdsEmptyDescription")
        description.setWordWrap(True)
        self.kds_record_count = QLabel("등록 레코드 0개")
        self.kds_record_count.setObjectName("kdsRecordCount")
        copy_button = QPushButton("선택 재료를 프로젝트에 추가")
        copy_button.setObjectName("materialSecondaryButton")
        copy_button.setDisabled(True)
        detail_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)
        detail_layout.addWidget(description, alignment=Qt.AlignmentFlag.AlignHCenter)
        detail_layout.addWidget(self.kds_record_count, alignment=Qt.AlignmentFlag.AlignHCenter)
        detail_layout.addSpacing(8)
        detail_layout.addWidget(copy_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        detail_layout.addStretch(1)
        layout.addWidget(detail, 1)

        self.kds_search.textChanged.connect(self._refresh_kds_results)
        self.kds_family.currentIndexChanged.connect(self._refresh_kds_database_options)
        self.kds_database.currentIndexChanged.connect(self._refresh_kds_results)
        self._refresh_kds_database_options()
        self._refresh_kds_results()
        return page

    def _build_user_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("materialTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("materialEditorSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_user_list())
        splitter.addWidget(self._build_editor())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((260, 800))
        layout.addWidget(splitter, 1)
        return page

    def _build_user_list(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("materialBrowserPanel")
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 11, 10, 10)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        title = QLabel("프로젝트 재료")
        title.setObjectName("materialPanelTitle")
        add_button = QPushButton("+  새 재료")
        add_button.setObjectName("materialListAddButton")
        add_button.clicked.connect(self._create_material)
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(add_button)
        layout.addLayout(heading)

        self.user_search = QLineEdit()
        self.user_search.setPlaceholderText("재료 검색…")
        self.user_list = QListWidget()
        self.user_list.setObjectName("userMaterialList")
        self.user_list.currentItemChanged.connect(self._material_selected)
        self.user_search.textChanged.connect(self._filter_user_list)
        layout.addWidget(self.user_search)
        layout.addWidget(self.user_list, 1)

        actions = QHBoxLayout()
        self.duplicate_button = QPushButton("복제")
        self.duplicate_button.setObjectName("materialSecondaryButton")
        self.duplicate_button.clicked.connect(self._duplicate_material)
        self.remove_button = QPushButton("삭제")
        self.remove_button.setObjectName("materialDangerButton")
        self.remove_button.clicked.connect(self._remove_material)
        actions.addWidget(self.duplicate_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        actions.addWidget(self.material_count)
        layout.addLayout(actions)
        return panel

    def _build_editor(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("materialEditorPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 12, 18, 10)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("재료 편집기")
        title.setObjectName("materialEditorTitle")
        source = QLabel("USER-DEFINED")
        source.setObjectName("materialIdBadge")
        heading.addWidget(title)
        heading.addWidget(source)
        heading.addStretch(1)
        layout.addLayout(heading)

        self.material_id_label = QLineEdit()
        self.material_id_label.setReadOnly(True)
        self.name_input = QLineEdit()
        self.family_input = QComboBox()
        for family, label in FAMILY_LABELS.items():
            self.family_input.addItem(label, family)
        self.opensees_model_input = QComboBox()
        # Presentation only. Nonlinear model behavior is owned by a separate workstream.
        self.opensees_model_input.addItems(
            ("Elastic", "ElasticPP", "Steel01", "Steel02", "Concrete01", "Concrete02")
        )
        self.elastic_modulus_input = self._number_input(decimals=6)
        self.poisson_ratio_input = self._number_input(decimals=5, maximum=0.49999)
        self.poisson_ratio_input.setMinimum(-0.99999)
        self.density_input = self._number_input(decimals=6)
        self.thermal_input = self._number_input(decimals=9)
        self.yield_input = self._number_input(decimals=6)
        self.compressive_input = self._number_input(decimals=6)
        self.tensile_input = self._number_input(decimals=6)
        self.shear_modulus_display = QLineEdit()
        self.shear_modulus_display.setReadOnly(True)
        self.shear_modulus_display.setObjectName("derivedMaterialValue")

        basic, basic_grid = self._property_group("기본 정보")
        self._field_row(basic_grid, 0, "재료 ID", self.material_id_label, "")
        self._field_row(basic_grid, 1, "재료명", self.name_input, "")
        self._field_row(basic_grid, 2, "재료 분류", self.family_input, "")
        self._field_row(basic_grid, 3, "OpenSees 모델", self.opensees_model_input, "")
        layout.addWidget(basic)

        elastic, elastic_grid = self._property_group("탄성 및 질량 특성")
        self.elastic_modulus_unit = self._field_row(
            elastic_grid, 0, "탄성계수 (E)", self.elastic_modulus_input, ""
        )
        self._field_row(elastic_grid, 1, "포아송비 (ν)", self.poisson_ratio_input, "—")
        self.shear_modulus_unit = self._field_row(
            elastic_grid, 2, "전단탄성계수 (G)", self.shear_modulus_display, ""
        )
        self.density_unit = self._field_row(
            elastic_grid, 3, "밀도 (ρ)", self.density_input, ""
        )
        self._field_row(elastic_grid, 4, "열팽창계수 (α)", self.thermal_input, "1/°C")
        layout.addWidget(elastic)

        strength, strength_grid = self._property_group("강도 특성")
        self.yield_strength_unit = self._field_row(
            strength_grid, 0, "항복강도 (Fy)", self.yield_input, ""
        )
        self.compressive_strength_unit = self._field_row(
            strength_grid, 1, "압축강도 (Fc)", self.compressive_input, ""
        )
        self.tensile_strength_unit = self._field_row(
            strength_grid, 2, "인장강도 (Ft)", self.tensile_input, ""
        )
        layout.addWidget(strength)

        self.elastic_modulus_input.valueChanged.connect(self._refresh_derived_shear)
        self.poisson_ratio_input.valueChanged.connect(self._refresh_derived_shear)
        layout.addWidget(self._build_shear_panel())

        self.validation_message = QLabel()
        self.validation_message.setObjectName("materialValidation")
        self.validation_message.setWordWrap(True)
        layout.addWidget(self.validation_message)
        layout.addStretch(1)
        self.save_button = QPushButton("재료 저장")
        self.save_button.setObjectName("materialPrimaryButton")
        self.save_button.clicked.connect(self._save_material)
        layout.addWidget(self.save_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.set_unit_system(self._unit_system)
        return panel

    @staticmethod
    def _property_group(title: str) -> tuple[QFrame, QGridLayout]:
        group = QFrame()
        group.setObjectName("materialPropertyGroup")
        outer = QVBoxLayout(group)
        outer.setContentsMargins(0, 0, 0, 8)
        outer.setSpacing(7)
        header = QLabel(title)
        header.setObjectName("materialPropertyGroupTitle")
        outer.addWidget(header)
        grid = QGridLayout()
        grid.setContentsMargins(14, 0, 14, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)
        return group, grid

    @staticmethod
    def _field_row(
        grid: QGridLayout,
        row: int,
        label: str,
        editor: QWidget,
        unit: str,
    ) -> QLabel:
        name = QLabel(label)
        name.setObjectName("materialFieldLabel")
        name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        unit_label = QLabel(unit)
        unit_label.setObjectName("materialUnitLabel")
        unit_label.setMinimumWidth(48)
        grid.addWidget(name, row, 0)
        grid.addWidget(editor, row, 1)
        grid.addWidget(unit_label, row, 2)
        return unit_label

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        stress_labels = (
            self.elastic_modulus_unit,
            self.shear_modulus_unit,
            self.yield_strength_unit,
            self.compressive_strength_unit,
            self.tensile_strength_unit,
        )
        for label in stress_labels:
            label.setText(unit_system.stress)
        self.density_unit.setText(unit_system.volumetric_force)

    def _build_shear_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("shearSettingsPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)
        title = QLabel("고급 옵션: 전단변형 고려")
        title.setObjectName("materialSectionHint")
        layout.addWidget(title)
        layout.addStretch(1)
        self.shear_enabled = QCheckBox("사용")
        self.shear_mode = QComboBox()
        self.shear_mode.addItem("E와 ν에서 G 자동 계산", ShearModulusMode.DERIVED_FROM_POISSON)
        self.shear_mode.addItem("G 직접 입력", ShearModulusMode.USER_DEFINED)
        self.shear_modulus_input = self._number_input(decimals=6)
        self.shear_modulus_input.setPrefix("G  ")
        self.shear_ky_input = self._number_input(decimals=6, maximum=10.0)
        self.shear_ky_input.setValue(5.0 / 6.0)
        self.shear_ky_input.setPrefix("κy  ")
        self.shear_kz_input = self._number_input(decimals=6, maximum=10.0)
        self.shear_kz_input.setValue(5.0 / 6.0)
        self.shear_kz_input.setPrefix("κz  ")
        layout.addWidget(self.shear_enabled)
        layout.addWidget(self.shear_mode)
        layout.addWidget(self.shear_modulus_input)
        layout.addWidget(self.shear_ky_input)
        layout.addWidget(self.shear_kz_input)
        self.shear_enabled.toggled.connect(self._refresh_shear_controls)
        self.shear_mode.currentIndexChanged.connect(self._refresh_shear_controls)
        self._refresh_shear_controls()
        return panel

    def shear_settings(self) -> ShearDeformationSettings:
        return ShearDeformationSettings(
            enabled=self.shear_enabled.isChecked(),
            modulus_mode=self.shear_mode.currentData(),
            user_shear_modulus=self.shear_modulus_input.value(),
            correction_factor_y=self.shear_ky_input.value(),
            correction_factor_z=self.shear_kz_input.value(),
        )

    def current_material(self) -> MaterialDefinition | None:
        if self._selected_material_id is None:
            return None
        return next(
            (
                material
                for material in self.library.user_materials()
                if material.material_id == self._selected_material_id
            ),
            None,
        )

    def _create_material(self) -> None:
        material = self.library.create_user_material()
        self._refresh_user_list(select_id=material.material_id)
        self.source_tabs.setCurrentIndex(1)

    def _duplicate_material(self) -> None:
        current = self._material_from_fields()
        if current is None:
            return
        duplicate = self.library.duplicate_as_user_material(current)
        self._refresh_user_list(select_id=duplicate.material_id)

    def _remove_material(self) -> None:
        if self._selected_material_id is None:
            return
        self.library.remove_user_material(self._selected_material_id)
        self._selected_material_id = None
        self._refresh_user_list()
        if not self.library.user_materials():
            self._create_material()

    def _save_material(self) -> None:
        material = self._material_from_fields()
        if material is None:
            return
        errors = material.validate()
        if errors:
            self.validation_message.setText(" · ".join(errors))
            self.validation_message.setProperty("state", "error")
            self._repolish(self.validation_message)
            return
        self.library.save_user_material(material)
        self._refresh_user_list(select_id=material.material_id)
        self.validation_message.setText("저장됨")
        self.validation_message.setProperty("state", "saved")
        self._repolish(self.validation_message)

    def _material_from_fields(self) -> MaterialDefinition | None:
        current = self.current_material()
        if current is None:
            return None
        return current.with_changes(
            name=self.name_input.text().strip(),
            family=self.family_input.currentData(),
            opensees_model=self.opensees_model_input.currentText(),
            elastic_modulus=self.elastic_modulus_input.value(),
            poisson_ratio=self.poisson_ratio_input.value(),
            density=self.density_input.value(),
            thermal_expansion=self.thermal_input.value(),
            yield_strength=self._optional_strength(self.yield_input.value()),
            compressive_strength=self._optional_strength(self.compressive_input.value()),
            tensile_strength=self._optional_strength(self.tensile_input.value()),
        )

    def _material_selected(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        material_id = current.data(Qt.ItemDataRole.UserRole)
        material = next(
            (
                item
                for item in self.library.user_materials()
                if item.material_id == material_id
            ),
            None,
        )
        if material is None:
            return
        self._selected_material_id = material.material_id
        self.material_id_label.setText(material.material_id)
        self.name_input.setText(material.name)
        self.family_input.setCurrentIndex(self.family_input.findData(material.family))
        self.opensees_model_input.setCurrentText(material.opensees_model)
        self.elastic_modulus_input.setValue(material.elastic_modulus)
        self.poisson_ratio_input.setValue(material.poisson_ratio)
        self.density_input.setValue(material.density)
        self.thermal_input.setValue(material.thermal_expansion)
        self.yield_input.setValue(material.yield_strength or 0.0)
        self.compressive_input.setValue(material.compressive_strength or 0.0)
        self.tensile_input.setValue(material.tensile_strength or 0.0)
        self._refresh_derived_shear()
        self.validation_message.clear()

    def _refresh_user_list(self, select_id: str | None = None) -> None:
        query = self.user_search.text().strip().casefold()
        self.user_list.blockSignals(True)
        self.user_list.clear()
        selected_item = None
        for material in self.library.user_materials():
            if query and query not in material.name.casefold():
                continue
            item = QListWidgetItem(
                f"{material.name}\n{FAMILY_LABELS[material.family]} · {material.opensees_model}"
            )
            item.setData(Qt.ItemDataRole.UserRole, material.material_id)
            self.user_list.addItem(item)
            if material.material_id == select_id:
                selected_item = item
        self.user_list.blockSignals(False)
        self.material_count.setText(f"재료 {len(self.library.user_materials())}")
        if selected_item is not None:
            self.user_list.setCurrentItem(selected_item)
            self._material_selected(selected_item, None)
        elif self.user_list.count():
            self.user_list.setCurrentRow(0)

    def _filter_user_list(self) -> None:
        self._refresh_user_list(select_id=self._selected_material_id)

    def _refresh_kds_results(self) -> None:
        records = self.library.search_kds(
            self.kds_search.text(),
            self.kds_family.currentData(),
        )
        self.kds_list.clear()
        for material in records:
            self.kds_list.addItem(material.name)
        self.kds_record_count.setText(f"등록 레코드 {len(records)}개")

    def _refresh_kds_database_options(self) -> None:
        family = self.kds_family.currentData()
        database_options = {
            MaterialFamily.CONCRETE: (("KDS 콘크리트 재료 DB", "kds_concrete"),),
            MaterialFamily.STRUCTURAL_STEEL: (("KDS 구조용 강재 DB", "kds_steel"),),
            MaterialFamily.REINFORCING_STEEL: (("KDS 철근 재료 DB", "kds_rebar"),),
            MaterialFamily.ELASTIC_ISOTROPIC: (("일반 탄성재료 DB", "elastic"),),
            MaterialFamily.OTHER: (("기타 재료 DB", "other"),),
            None: (("전체 KDS 재료 DB", "all"),),
        }
        self.kds_database.blockSignals(True)
        self.kds_database.clear()
        for label, key in database_options[family]:
            self.kds_database.addItem(label, key)
        self.kds_database.blockSignals(False)
        self._refresh_kds_results()

    def _refresh_shear_controls(self) -> None:
        enabled = self.shear_enabled.isChecked()
        manual = self.shear_mode.currentData() == ShearModulusMode.USER_DEFINED
        self.shear_mode.setVisible(enabled)
        self.shear_modulus_input.setVisible(enabled and manual)
        self.shear_ky_input.setVisible(enabled)
        self.shear_kz_input.setVisible(enabled)

    def _refresh_derived_shear(self) -> None:
        denominator = 2.0 * (1.0 + self.poisson_ratio_input.value())
        value = self.elastic_modulus_input.value() / denominator if denominator > 0.0 else 0.0
        self.shear_modulus_display.setText(f"{value:.6g}")

    @staticmethod
    def _number_input(decimals: int, maximum: float = 1.0e15) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setDecimals(decimals)
        field.setRange(0.0, maximum)
        field.setKeyboardTracking(False)
        field.setAlignment(Qt.AlignmentFlag.AlignRight)
        return field

    @staticmethod
    def _optional_strength(value: float) -> float | None:
        return value if value > 0.0 else None

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
