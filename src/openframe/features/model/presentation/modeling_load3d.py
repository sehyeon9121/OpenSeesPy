"""3D Loads tab (cases, entries, generators, combinations) for ModelingInterfacePage.

Mixin: mutates ``self.canvas`` load stores and refreshes the 3D load glyphs.
Split out of the page so load-command work does not pull in 3D picking or
Work Tree geometry rows. ``build_model()`` is only used when generating
seismic/wind forces (a button press), never on every click.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    FloorLoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoadEntry,
    SeismicLoadParameters,
    SelfWeightEntry,
    StoryWeight,
    WindLoadParameters,
    design_spectral_accelerations,
    equivalent_lateral_force,
    lumped_node_weights,
    mpa_to_stress_unit,
    seismic_response_coefficient,
    wind_force_by_story,
)
from openframe.features.model.presentation.current_page_only_stack import _CurrentPageOnlyStack
from openframe.features.model.presentation.floor_load_type_manager_dialog import (
    FloorLoadTypeManagerDialog,
)
from openframe.features.model.presentation.load_case_manager_dialog import LoadCaseManagerDialog
from openframe.features.model.presentation.load_combination_manager_dialog import (
    LoadCombinationManagerDialog,
)
from openframe.features.model.presentation.model_sidebar import LOAD_CASE_PRESENTATION
from openframe.features.model.presentation.modeling_tree_roles import (
    _TREE_DEFINITION_ROLE,
    _TREE_ENTITY_ROLE,
    _LoadTreeBinding,
)
from openframe.features.model.presentation.safe_spinbox import (
    DownwardComboBox,
    SafeComboBox,
    SafeDoubleSpinBox,
    SafeSpinBox,
)


class _Load3DPanelMixin:

    def _build_load_task_bar(self) -> QFrame:
        """Viewport-only load display controls.

        Load Case authoring/selection belongs to the left Loads command
        panel.  Keeping it here as well made the user scan two distant
        places before one load could be entered.  This bar therefore owns
        only visualisation state: what is drawn, glyph scale and labels.
        """
        bar = QFrame()
        bar.setObjectName("loadTaskBar")
        self.load_task_bar = bar
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        layout.addWidget(QLabel("하중 표시"))
        self.load_display_combo = QComboBox()
        self.load_display_combo.addItem("Current Load Case", "case")
        self.load_display_combo.addItem("Load Combination", "combination")
        self.load_display_combo.addItem("All Loads", "all")
        self.load_display_combo.addItem("Hide Loads", "hidden")
        self.load_display_combo.currentIndexChanged.connect(self._on_load_display_mode_changed)
        layout.addWidget(self.load_display_combo)

        layout.addWidget(QLabel("Load Scale"))
        scale_minus = QPushButton("-")
        scale_minus.setFixedWidth(24)
        scale_minus.clicked.connect(lambda: self._nudge_load_scale(-10))
        layout.addWidget(scale_minus)
        self.load_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.load_scale_slider.setRange(10, 300)
        self.load_scale_slider.setValue(100)
        self.load_scale_slider.setFixedWidth(120)
        self.load_scale_slider.setToolTip("뷰포트에 그려지는 하중 글리프의 크기 배율(%)")
        self.load_scale_slider.valueChanged.connect(lambda _value: self._refresh_load3d_viewport())
        layout.addWidget(self.load_scale_slider)
        scale_plus = QPushButton("+")
        scale_plus.setFixedWidth(24)
        scale_plus.clicked.connect(lambda: self._nudge_load_scale(10))
        layout.addWidget(scale_plus)

        self.load_value_labels_checkbox = QCheckBox("Value Labels")
        layout.addWidget(self.load_value_labels_checkbox)

        layout.addStretch(1)
        self.load_readonly_hint = QLabel("읽기 전용 미리보기 - 하중조합 표시 중에는 입력할 수 없습니다.")
        self.load_readonly_hint.setObjectName("setupSectionHint")
        self.load_readonly_hint.setVisible(False)
        layout.addWidget(self.load_readonly_hint)

        # The bar is shown only while Loads is active. It is deliberately
        # separate from authoring data and contains no management action.
        bar.setVisible(False)
        return bar


    def _refresh_load_case_combo(self) -> None:
        if not hasattr(self, "load_case_combo"):
            return
        self.load_case_combo.blockSignals(True)
        self.load_case_combo.clear()
        for case in self.canvas.load_cases.values():
            self.load_case_combo.addItem(case.name, case.id)
        index = self.load_case_combo.findData(self.canvas.active_load_case_id)
        if index >= 0:
            self.load_case_combo.setCurrentIndex(index)
        self.load_case_combo.blockSignals(False)


    def _refresh_load_combination_combo(self) -> None:
        for combo in (
            getattr(self, "load_combination_combo", None),
            getattr(self, "make_load_combination_combo", None),
        ):
            if combo is None:
                continue
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for combination in self.canvas.load_combinations.values():
                combo.addItem(combination.name, combination.name)
            selected = previous or self.canvas.active_combination_id
            index = combo.findData(selected)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)


    def _on_load_case_combo_changed(self, _index: int) -> None:
        self.canvas.active_load_case_id = self.load_case_combo.currentData()


    def _on_load_combination_combo_changed(self, _index: int) -> None:
        self.canvas.active_combination_id = self.load_combination_combo.currentData()
        if self.load_display_mode_key() == "combination":
            self._refresh_load3d_viewport()


    def load_display_mode_key(self) -> str:
        return self.load_display_combo.currentData() or "case"


    def _on_load_display_mode_changed(self, _index: int) -> None:
        mode = self.load_display_mode_key()
        self.canvas.load_display_mode = mode
        read_only = mode == "combination"
        self.load_readonly_hint.setVisible(read_only)
        if hasattr(self, "load3d_apply_button"):
            self.load3d_apply_button.setEnabled(not read_only)
        if hasattr(self, "load_apply_button"):
            self.load_apply_button.setEnabled(not read_only)
        for group in (
            getattr(self, "load3d_type_group", None),
            getattr(self, "load3d_member_subtype_group", None),
        ):
            if group is not None:
                for button in group.buttons():
                    button.setEnabled(not read_only)
        if hasattr(self, "load3d_form_stack"):
            self.load3d_form_stack.setEnabled(not read_only)
        self._refresh_load3d_viewport()


    def _nudge_load_scale(self, delta: int) -> None:
        self.load_scale_slider.setValue(self.load_scale_slider.value() + delta)


    def _open_load_case_manager(self) -> None:
        dialog = LoadCaseManagerDialog(self.canvas, self)
        dialog.exec()


    def _open_load_combination_manager(self) -> None:
        dialog = LoadCombinationManagerDialog(self.canvas, self)
        dialog.exec()


    def _open_floor_load_type_manager(self) -> None:
        dialog = FloorLoadTypeManagerDialog(self.canvas, unit_system=self._unit_system, parent=self)
        dialog.exec()


    def _refresh_floor_load_type_combo(self) -> None:
        if not hasattr(self, "load3d_floor_type_combo"):
            return
        combo = self.load3d_floor_type_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(직접 입력)", None)
        for floor_type in self.canvas.floor_load_types.values():
            combo.addItem(floor_type.name, floor_type.id)
        index = combo.findData(previous)
        combo.setCurrentIndex(max(index, 0))
        combo.blockSignals(False)


    def _apply_floor_load_type(self) -> None:
        type_id = self.load3d_floor_type_combo.currentData()
        if type_id is None:
            self.load3d_status_label.setText("⚠ 먼저 Floor Load Type을 선택하세요.")
            return
        targets = tuple(sorted(self.canvas.selected_nodes))
        if len(targets) < 3:
            self.load3d_status_label.setText("⚠ 폐합영역을 이룰 절점을 3개 이상 선택하세요.")
            return
        count = self.canvas.apply_floor_load_type(
            type_id,
            targets,
            direction=self.load3d_floor_direction.currentData(),
            distribution=self.load3d_floor_distribution.currentData(),
            span_direction=self.load3d_floor_span_direction.currentData(),
        )
        if not count:
            self.load3d_status_label.setText("⚠ 이 타입에는 적용할 하중이 없습니다 (모든 행이 NONE이거나 0).")
            return
        self.load3d_status_label.setText(f"✓ {count}개 케이스의 하중을 한번에 적용했습니다.")
        self._refresh_load3d_viewport()


    def _refresh_load3d_viewport(self) -> None:
        """Repaint the Loads tab's case-based glyphs (Quick3DSceneBridge.
        loadEntryGlyphs) - kept as its own method so every state change that
        should repaint the viewport (load CRUD, Display mode, Load Scale,
        set_model()'s own geometry rebuild) calls it exactly once."""
        preview = getattr(self, "preview_3d", None)
        if preview is not None and hasattr(preview, "set_load_entries"):
            preview.set_load_entries(
                self.canvas.load_entries,
                self.canvas.load_cases,
                self.canvas.load_combinations,
                mode=self.load_display_mode_key(),
                active_case_id=self.canvas.active_load_case_id,
                active_combination_id=self.canvas.active_combination_id,
                scale=self.load_scale_slider.value() / 100.0 if hasattr(self, "load_scale_slider") else 1.0,
            )


    #: Logical groups shown inside the single MIDAS-style command picker.
    #: Prefixes make the hierarchy explicit without spending two full rows
    #: on four category buttons before the actual load type can be chosen.
    _LOAD_CATEGORY_OPTIONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("definitions", "Definitions"),
        ("direct", "Direct Loads"),
        ("generators", "Load Generators"),
        ("combinations", "Load Combinations"),
    )


    _LOAD_COMMAND_OPTIONS: ClassVar[
        tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    ] = (
        ("definitions", (("load_cases", "Load Cases"),)),
        (
            "direct",
            (
                ("self_weight", "Self-Weight"),
                ("nodal", "Nodal Load"),
                ("member_point", "Member Point Load"),
                ("member_uniform", "Uniform Member Load"),
                ("member_linear", "Linearly Varying Member Load"),
                ("member_partial", "Partial-Span Member Load"),
                ("member_moment", "Member Point Moment"),
                ("floor", "Assign Floor Load"),
            ),
        ),
        (
            "generators",
            (("wind", "Wind Load"), ("seismic", "Static Seismic Load")),
        ),
        (
            "combinations",
            (
                ("load_combinations", "Load Combinations"),
                ("make_combination", "Create Case from Combination"),
            ),
        ),
    )


    def _build_3d_load_category(self) -> QWidget:
        """MIDAS-style Loads editor: one command, one compact settings flow.

        The previous 2x2 category buttons followed by another Type dropdown
        consumed two navigation rows and made the controls look unrelated.
        A single grouped command picker now carries both levels.  The pages
        below remain persistent, so switching commands never discards typed
        values.
        """
        section = QWidget()
        root = QVBoxLayout(section)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        command_bar = QFrame()
        command_bar.setObjectName("loadCommandBar")
        command_layout = QHBoxLayout(command_bar)
        command_layout.setContentsMargins(10, 7, 10, 7)
        command_layout.setSpacing(8)
        command_label = QLabel("LOAD")
        command_label.setObjectName("fieldLabel")
        command_layout.addWidget(command_label)
        self.load_command_combo = DownwardComboBox()
        self.load_command_combo.setObjectName("loadCommandCombo")
        self.load_command_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        category_labels = dict(self._LOAD_CATEGORY_OPTIONS)
        for group_index, (category, commands) in enumerate(self._LOAD_COMMAND_OPTIONS):
            if group_index:
                self.load_command_combo.insertSeparator(self.load_command_combo.count())
            prefix = category_labels[category]
            for key, label in commands:
                self.load_command_combo.addItem(f"[{prefix}] {label}", key)
        command_layout.addWidget(self.load_command_combo, 1)
        root.addWidget(command_bar)

        self.load_category_stack = _CurrentPageOnlyStack()
        self.load_category_pages = {
            "definitions": self.load_category_stack.addWidget(self._build_load_definitions_page()),
            "direct": self.load_category_stack.addWidget(self._build_load_direct_page()),
            "generators": self.load_category_stack.addWidget(self._build_load_generators_page()),
            "combinations": self.load_category_stack.addWidget(self._build_load_combinations_page()),
        }
        root.addWidget(self.load_category_stack)

        self.load_command_combo.currentIndexChanged.connect(self._on_load_command_changed)
        self.load_command_combo.setCurrentIndex(self.load_command_combo.findData("nodal"))
        self._on_load_command_changed()
        return section


    def _on_load_category_changed(self, key: str) -> None:
        first_command = dict(self._LOAD_COMMAND_OPTIONS)[key][0][0]
        index = self.load_command_combo.findData(first_command)
        if index >= 0:
            self.load_command_combo.setCurrentIndex(index)

    @staticmethod
    def _load_group_card(title: str) -> tuple[QFrame, QVBoxLayout]:
        """A compact titled group shared by every Loads command page."""
        card = QFrame()
        card.setObjectName("loadGroupCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 9)
        layout.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("loadGroupTitle")
        layout.addWidget(heading)
        return card, layout


    def _build_load_definitions_page(self) -> QWidget:
        return self._build_load_case_command_page()


    def _build_load_direct_page(self) -> QWidget:
        """Shared assignment context followed by one command-specific form."""
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(8)

        context_card, context = self._load_group_card("적용 정보")
        case_form = QFormLayout()
        case_form.setContentsMargins(0, 0, 0, 0)
        case_row = QHBoxLayout()
        case_row.setContentsMargins(0, 0, 0, 0)
        case_row.setSpacing(6)
        self.load_case_combo = QComboBox()
        self.load_case_combo.currentIndexChanged.connect(self._on_load_case_combo_changed)
        case_row.addWidget(self.load_case_combo, 1)
        case_manage_button = QPushButton("...")
        case_manage_button.setObjectName("loadEllipsisButton")
        case_manage_button.setToolTip("하중케이스 관리")
        case_manage_button.clicked.connect(self._open_load_case_manager)
        case_row.addWidget(case_manage_button)
        case_form.addRow("하중케이스", case_row)
        context.addLayout(case_form)

        self.load_apply_mode_group = QButtonGroup(self)
        self.load_apply_mode_group.setExclusive(True)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        mode_row.addWidget(QLabel("작업"))
        self.load_apply_mode_buttons: dict[str, QRadioButton] = {}
        for label, key in (("추가", "add"), ("교체", "replace"), ("삭제", "delete")):
            button = QRadioButton(label)
            self.load_apply_mode_group.addButton(button)
            self.load_apply_mode_buttons[key] = button
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        self.load_apply_mode_buttons["replace"].setChecked(True)
        self.load_apply_mode_group.buttonToggled.connect(
            lambda _button, _checked: self._on_load_apply_mode_changed()
        )
        context.addLayout(mode_row)
        root.addWidget(context_card)

        self.canvas.load_state_changed.connect(self._refresh_load_case_combo)
        self._refresh_load_case_combo()

        self.load_command_stack = _CurrentPageOnlyStack()
        self.load_command_pages = {
            "quick": self.load_command_stack.addWidget(
                self._build_load_bar_content(command_driven=True)
            ),
            "entry": self.load_command_stack.addWidget(
                self._build_3d_load_manager_content()
            ),
        }
        settings_card = QFrame()
        settings_card.setObjectName("loadSettingsCard")
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(10, 9, 10, 9)
        settings_layout.addWidget(self.load_command_stack)
        root.addWidget(settings_card)
        return page


    def _build_load_combinations_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(8)

        # Kept as an internal state selector for existing edit/refresh paths;
        # navigation is exposed only once, by the master LOAD picker above.
        self.load_combinations_subnav_combo = DownwardComboBox(page)
        self.load_combinations_subnav_combo.addItem("Load Combinations", "load_combinations")
        self.load_combinations_subnav_combo.addItem("New Case", "make_combination")
        self.load_combinations_subnav_combo.hide()

        self.load_combinations_stack = _CurrentPageOnlyStack()
        self.load_combinations_pages = {
            "load_combinations": self.load_combinations_stack.addWidget(
                self._build_load_combination_command_page()
            ),
            "make_combination": self.load_combinations_stack.addWidget(
                self._build_make_load_case_command_page()
            ),
        }
        root.addWidget(self.load_combinations_stack)
        self.load_combinations_subnav_combo.currentIndexChanged.connect(
            self._on_load_combinations_subnav_changed
        )
        self.load_combinations_subnav_combo.setCurrentIndex(0)
        self._on_load_combinations_subnav_changed()
        return page


    def _on_load_combinations_subnav_changed(self, _index: int | None = None) -> None:
        key = str(self.load_combinations_subnav_combo.currentData())
        self.load_combinations_stack.setCurrentIndex(self.load_combinations_pages[key])


    def _build_load_generators_page(self) -> QWidget:
        """Wind Load / Static Seismic Load - placeholders only. No formula,
        no automatic generation; see _build_3d_load_category's docstring."""
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(8)

        self.load_generators_subnav_combo = DownwardComboBox(page)
        self.load_generators_subnav_combo.addItem("Wind Load", "wind")
        self.load_generators_subnav_combo.addItem("Static Seismic Load", "seismic")
        self.load_generators_subnav_combo.hide()

        self.load_generators_stack = _CurrentPageOnlyStack()
        self.load_generators_pages = {
            "wind": self.load_generators_stack.addWidget(self._build_wind_load_generator_page()),
            "seismic": self.load_generators_stack.addWidget(
                self._build_seismic_load_generator_page()
            ),
        }
        root.addWidget(self.load_generators_stack)
        self.load_generators_subnav_combo.currentIndexChanged.connect(
            self._on_load_generators_subnav_changed
        )
        self.load_generators_subnav_combo.setCurrentIndex(0)
        self._on_load_generators_subnav_changed()
        return page


    def _on_load_generators_subnav_changed(self, _index: int | None = None) -> None:
        key = str(self.load_generators_subnav_combo.currentData())
        self.load_generators_stack.setCurrentIndex(self.load_generators_pages[key])


    def _build_load_generator_placeholder(self, title: str, message: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        card, content = self._load_group_card(title)
        hint = QLabel(message)
        hint.setObjectName("loadModeHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        content.addWidget(hint)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    @staticmethod
    def _add_generator_field(
        layout: QVBoxLayout,
        label: str,
        field: QWidget,
        help_text: str = "",
    ) -> QLabel:
        """Stack a full-name load parameter above its control.

        The Loads dock is intentionally only 320 px wide. A conventional
        QFormLayout forces a long engineering name and its input into one
        narrow row, which is why the old UI fell back to unexplained symbols
        such as Ss/Fa/R. Stacking keeps the complete name readable and still
        leaves the input at a comfortable width.
        """
        title = QLabel(label)
        title.setObjectName("loadParameterLabel")
        title.setWordWrap(True)
        title.setMaximumWidth(272)
        layout.addWidget(title)
        field.setMaximumWidth(272)
        field.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            field.sizePolicy().verticalPolicy(),
        )
        layout.addWidget(field)
        if help_text:
            hint = QLabel(help_text)
            hint.setObjectName("loadParameterHelp")
            hint.setWordWrap(True)
            hint.setMaximumWidth(272)
            layout.addWidget(hint)
        return title

    @staticmethod
    def _generator_row(*widgets: QWidget) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        for index, widget in enumerate(widgets):
            row_layout.addWidget(widget, 1 if index == 0 else 0)
        return row


    def _build_seismic_load_generator_page(self) -> QWidget:
        """Compact launcher for a tabbed KDS Equivalent Lateral Force setup.

        The Loads sidebar only keeps the current specification summary and
        actions. Full-name engineering inputs live in a small modal window,
        grouped into four tabs instead of forming one very long left column.
        Formula results are automatic, while edition/site/system lookup-table
        values remain explicit engineer inputs.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        self.seismic_settings_dialog = QDialog(self)
        self.seismic_settings_dialog.setObjectName("seismicSettingsDialog")
        self.seismic_settings_dialog.setWindowTitle("정적 지진하중 설정")
        self.seismic_settings_dialog.resize(460, 720)
        dialog_layout = QVBoxLayout(self.seismic_settings_dialog)
        dialog_layout.setContentsMargins(10, 10, 10, 10)
        dialog_layout.setSpacing(8)
        self.seismic_settings_tabs = QTabWidget()
        self.seismic_settings_tabs.setObjectName("seismicSettingsTabs")
        dialog_layout.addWidget(self.seismic_settings_tabs, 1)

        def add_settings_tab(card_widget: QWidget, label: str) -> None:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            )
            scroll.setWidget(card_widget)
            self.seismic_settings_tabs.addTab(scroll, label)

        card, content = self._load_group_card("기본 설정")
        self.seismic_code_combo = SafeComboBox()
        self.seismic_code_combo.addItem(
            "KDS 41 17 00:2019 — 건축물 내진설계기준",
            "KDS 41 17 00:2019",
        )
        self.seismic_code_combo.addItem("사용자 지정 설계기준", "custom")
        self._add_generator_field(content, "설계기준 (Seismic Load Code)", self.seismic_code_combo)
        self.seismic_description = QLineEdit()
        self.seismic_description.setPlaceholderText("예: X방향 등가정적 지진하중")
        self._add_generator_field(content, "설명 (Description)", self.seismic_description)

        self.seismic_case_combo = SafeComboBox()
        self.seismic_case_combo.setToolTip(
            "이 케이스에 이미 있는 하중은 생성할 때마다 계산된 값으로 대체됩니다."
        )
        case_manage_button = QPushButton("관리...")
        case_manage_button.clicked.connect(self._open_load_case_manager)
        self._add_generator_field(
            content,
            "적용할 하중케이스 (Load Case)",
            self._generator_row(self.seismic_case_combo, case_manage_button),
            "지진하중 전용 케이스를 권장합니다.",
        )
        content.addStretch(1)
        add_settings_tab(card, "기본")

        ground_card, ground = self._load_group_card("설계 스펙트럼과 지반")
        hint = QLabel(
            "지반종류는 검토 기록용이며, Fa·Fv는 선택한 규준판의 표에서 확인해 "
            "직접 입력합니다. SDS와 SD1은 입력과 동시에 계산됩니다."
        )
        hint.setObjectName("loadModeHint")
        hint.setWordWrap(True)
        hint.setMaximumWidth(272)
        ground.addWidget(hint)
        self.seismic_site_class = SafeComboBox()
        for site_class in ("S1", "S2", "S3", "S4", "S5", "S6"):
            self.seismic_site_class.addItem(f"지반종류 {site_class}", site_class)
        self.seismic_site_class.setCurrentIndex(1)
        self._add_generator_field(
            ground,
            "지반종류 (Site Class)",
            self.seismic_site_class,
            "선택만으로 Fa·Fv를 자동 결정하지 않습니다.",
        )
        self.seismic_ss = SafeDoubleSpinBox()
        self.seismic_ss.setRange(0.0, 3.0)
        self.seismic_ss.setDecimals(3)
        self._add_generator_field(
            ground,
            "단주기 응답스펙트럼 가속도 Ss (g)",
            self.seismic_ss,
        )
        self.seismic_s1 = SafeDoubleSpinBox()
        self.seismic_s1.setRange(0.0, 2.0)
        self.seismic_s1.setDecimals(3)
        self._add_generator_field(
            ground,
            "1초주기 응답스펙트럼 가속도 S1 (g)",
            self.seismic_s1,
        )
        self.seismic_fa = SafeDoubleSpinBox()
        self.seismic_fa.setRange(0.1, 5.0)
        self.seismic_fa.setDecimals(3)
        self.seismic_fa.setValue(1.0)
        self._add_generator_field(
            ground,
            "단주기 지반증폭계수 Fa",
            self.seismic_fa,
            "선택한 지반종류와 Ss에 맞는 규준 표 값을 입력하세요.",
        )
        self.seismic_fv = SafeDoubleSpinBox()
        self.seismic_fv.setRange(0.1, 5.0)
        self.seismic_fv.setDecimals(3)
        self.seismic_fv.setValue(1.0)
        self._add_generator_field(
            ground,
            "1초주기 지반증폭계수 Fv",
            self.seismic_fv,
            "선택한 지반종류와 S1에 맞는 규준 표 값을 입력하세요.",
        )
        self.seismic_spectrum_summary = QLabel()
        self.seismic_spectrum_summary.setObjectName("loadDerivedValue")
        self.seismic_spectrum_summary.setWordWrap(True)
        ground.addWidget(self.seismic_spectrum_summary)
        ground.addStretch(1)
        add_settings_tab(ground_card, "설계 스펙트럼")

        structure_card, structure = self._load_group_card("구조 특성")
        self.seismic_system_description = QLineEdit()
        self.seismic_system_description.setPlaceholderText("예: 철골 보통모멘트골조")
        self._add_generator_field(
            structure,
            "지진력저항시스템 (Seismic Force-Resisting System)",
            self.seismic_system_description,
        )
        self.seismic_r = SafeDoubleSpinBox()
        self.seismic_r.setRange(0.1, 10.0)
        self.seismic_r.setDecimals(2)
        self.seismic_r.setValue(1.0)
        self._add_generator_field(
            structure,
            "반응수정계수 R (Response Modification Coefficient)",
            self.seismic_r,
            "지진력저항시스템별 규준 표 값을 입력하세요.",
        )
        self.seismic_ie = SafeDoubleSpinBox()
        self.seismic_ie.setRange(0.1, 2.0)
        self.seismic_ie.setDecimals(2)
        self.seismic_ie.setValue(1.0)
        self._add_generator_field(
            structure,
            "내진 중요도계수 Ie (Seismic Importance Factor)",
            self.seismic_ie,
        )
        self.seismic_period_method = SafeComboBox()
        self.seismic_period_method.addItem("직접 입력", "manual")
        self.seismic_period_method.addItem("고유치해석 결과 입력", "modal")
        self._add_generator_field(
            structure,
            "기본진동주기 입력방법 (Fundamental Period Method)",
            self.seismic_period_method,
        )
        self.seismic_period = SafeDoubleSpinBox()
        self.seismic_period.setRange(0.0, 20.0)
        self.seismic_period.setDecimals(3)
        self.seismic_period.setValue(0.5)
        self._add_generator_field(
            structure,
            "기본진동주기 T (s)",
            self.seismic_period,
            "고유치해석의 1차 주기 또는 규준의 근사주기를 입력하세요.",
        )
        self.seismic_coefficient_summary = QLabel()
        self.seismic_coefficient_summary.setObjectName("loadDerivedValue")
        self.seismic_coefficient_summary.setWordWrap(True)
        structure.addWidget(self.seismic_coefficient_summary)
        structure.addStretch(1)
        add_settings_tab(structure_card, "구조 특성")

        application_card, application = self._load_group_card("가력 방향과 우발편심")
        self.seismic_direction_combo = SafeComboBox()
        for label, key in (
            ("전역 +X 방향", "x"),
            ("전역 -X 방향", "-x"),
            ("전역 +Y 방향", "y"),
            ("전역 -Y 방향", "-y"),
        ):
            self.seismic_direction_combo.addItem(label, key)
        self._add_generator_field(
            application,
            "수평 지진하중 방향 (Loading Direction)",
            self.seismic_direction_combo,
        )
        self.seismic_scale_factor = SafeDoubleSpinBox()
        self.seismic_scale_factor.setRange(0.0, 100.0)
        self.seismic_scale_factor.setDecimals(3)
        self.seismic_scale_factor.setValue(1.0)
        self._add_generator_field(
            application,
            "방향 배율 (Direction Scale Factor)",
            self.seismic_scale_factor,
        )
        self.seismic_eccentricity_sign = SafeComboBox()
        self.seismic_eccentricity_sign.addItem("적용 안 함", 0.0)
        self.seismic_eccentricity_sign.addItem("양(+)의 편심", 1.0)
        self.seismic_eccentricity_sign.addItem("음(-)의 편심", -1.0)
        self._add_generator_field(
            application,
            "우발편심 방향 (Accidental Eccentricity)",
            self.seismic_eccentricity_sign,
        )
        self.seismic_eccentricity = SafeDoubleSpinBox()
        self.seismic_eccentricity.setRange(0.0, 1.0e6)
        self.seismic_eccentricity.setDecimals(4)
        self.seismic_eccentricity_label = self._add_generator_field(
            application,
            f"편심거리 e ({self._unit_system.length})",
            self.seismic_eccentricity,
            "평면치수의 비율이 아니라 실제 모델 길이입니다. 생성 하중에 Mz = F×e로 반영됩니다.",
        )
        self.seismic_eccentricity_sign.currentIndexChanged.connect(
            self._refresh_seismic_parameter_summary
        )
        application.addStretch(1)
        add_settings_tab(application_card, "가력·편심")

        self.canvas.load_state_changed.connect(self._refresh_seismic_case_combo)
        self._refresh_seismic_case_combo()

        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        dialog_buttons.accepted.connect(self.seismic_settings_dialog.accept)
        dialog_buttons.rejected.connect(self.seismic_settings_dialog.reject)
        dialog_layout.addWidget(dialog_buttons)

        summary_card, summary_layout = self._load_group_card("정적 지진하중")
        self.seismic_compact_summary = QLabel()
        self.seismic_compact_summary.setObjectName("seismicCompactSummary")
        self.seismic_compact_summary.setWordWrap(True)
        summary_layout.addWidget(self.seismic_compact_summary)

        self.seismic_settings_button = QPushButton("설정 열기...")
        self.seismic_settings_button.setObjectName("seismicSettingsButton")
        self.seismic_settings_button.clicked.connect(
            self._open_seismic_settings_dialog
        )
        summary_layout.addWidget(self.seismic_settings_button)

        generate_button = QPushButton("지진하중 생성")
        generate_button.setObjectName("loadPrimaryButton")
        generate_button.clicked.connect(self._generate_seismic_load)
        summary_layout.addWidget(generate_button)
        layout.addWidget(summary_card)

        self.seismic_result_label = QLabel()
        self.seismic_result_label.setWordWrap(True)
        self.seismic_result_label.setObjectName("loadModeHint")
        layout.addWidget(self.seismic_result_label)

        for field in (
            self.seismic_ss,
            self.seismic_s1,
            self.seismic_fa,
            self.seismic_fv,
            self.seismic_r,
            self.seismic_ie,
            self.seismic_period,
            self.seismic_scale_factor,
            self.seismic_eccentricity,
        ):
            field.valueChanged.connect(self._refresh_seismic_parameter_summary)
        for combo in (
            self.seismic_code_combo,
            self.seismic_case_combo,
            self.seismic_site_class,
            self.seismic_period_method,
            self.seismic_direction_combo,
        ):
            combo.currentIndexChanged.connect(self._refresh_seismic_parameter_summary)
        self._refresh_seismic_parameter_summary()

        layout.addStretch(1)
        return page


    def _open_seismic_settings_dialog(self) -> None:
        """Edit the sidebar's seismic specification without making the
        sidebar itself carry the full engineering form.

        The dialog owns the live widgets so derived values update while the
        user types. A rejected dialog restores the exact pre-open state,
        preserving ordinary OK/Cancel semantics despite that live preview.
        """
        self._refresh_seismic_case_combo()
        snapshot = dict(self._load_generator_settings()["seismic"])
        if self.seismic_settings_dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_seismic_parameter_summary()
            return
        self._restore_load_generator_settings({"seismic": snapshot})


    def _refresh_seismic_compact_summary(self) -> None:
        if not hasattr(self, "seismic_compact_summary"):
            return
        sds, sd1 = design_spectral_accelerations(
            self.seismic_ss.value(),
            self.seismic_fa.value(),
            self.seismic_s1.value(),
            self.seismic_fv.value(),
        )
        try:
            coefficient = seismic_response_coefficient(
                sds=sds,
                sd1=sd1,
                s1=self.seismic_s1.value(),
                r=self.seismic_r.value(),
                ie=self.seismic_ie.value(),
                period=self.seismic_period.value(),
            )
            coefficient_text = f"Cs {coefficient:.4f}"
        except ValueError:
            coefficient_text = "Cs 확인 필요"
        case_name = self.seismic_case_combo.currentText().strip() or "선택 안 함"
        self.seismic_compact_summary.setText(
            f"하중케이스 · {case_name}\n"
            f"가력방향 · {self.seismic_direction_combo.currentText()}\n"
            f"SDS {sds:.4f} g · SD1 {sd1:.4f} g · {coefficient_text}"
        )


    def _refresh_seismic_parameter_summary(self, _value: object | None = None) -> None:
        if not hasattr(self, "seismic_spectrum_summary"):
            return
        sds, sd1 = design_spectral_accelerations(
            self.seismic_ss.value(),
            self.seismic_fa.value(),
            self.seismic_s1.value(),
            self.seismic_fv.value(),
        )
        self.seismic_spectrum_summary.setText(
            f"자동 계산 · 단주기 설계스펙트럼 SDS = {sds:.4f} g\n"
            f"1초주기 설계스펙트럼 SD1 = {sd1:.4f} g"
        )
        try:
            coefficient = seismic_response_coefficient(
                sds=sds,
                sd1=sd1,
                s1=self.seismic_s1.value(),
                r=self.seismic_r.value(),
                ie=self.seismic_ie.value(),
                period=self.seismic_period.value(),
            )
            coefficient_text = f"Cs = {coefficient:.4f}"
        except ValueError as error:
            coefficient_text = str(error)
        reduction = self.seismic_r.value() / self.seismic_ie.value()
        self.seismic_coefficient_summary.setText(
            f"자동 계산 · R/Ie = {reduction:.3f} · {coefficient_text}"
        )
        use_eccentricity = float(self.seismic_eccentricity_sign.currentData()) != 0.0
        self.seismic_eccentricity.setEnabled(use_eccentricity)
        self._refresh_seismic_compact_summary()


    def _refresh_seismic_case_combo(self) -> None:
        if not hasattr(self, "seismic_case_combo"):
            return
        combo = self.seismic_case_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for case in self.canvas.load_cases.values():
            combo.addItem(case.name, case.id)
        index = combo.findData(previous)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self._refresh_seismic_compact_summary()


    def _generate_seismic_load(self) -> None:
        case_id = self.seismic_case_combo.currentData()
        if not case_id:
            self.seismic_result_label.setText(
                "먼저 '케이스 관리...'에서 지진하중을 담을 하중케이스를 만드세요."
            )
            return
        if not self.canvas.stories:
            self.seismic_result_label.setText(
                "Story Manager에서 층을 먼저 정의해야 층별로 힘을 분배할 수 있습니다."
            )
            return
        model = self.canvas.build_model()
        node_weights = lumped_node_weights(model)
        if sum(node_weights.values()) <= 0.0:
            self.seismic_result_label.setText(
                "부재에 밀도(단위중량)와 단면적(A)이 입력되지 않아 중량을 계산할 수 "
                "없습니다 - 부재 속성에서 재료를 입력하세요."
            )
            return

        # The base is the model's own lowest node (the foundation level a
        # real building's supports sit at), not the lowest *Story* - a
        # building's first defined story is usually well above its
        # foundation, and treating that as height-zero would wrongly zero
        # out its own share of the seismic force (see
        # ``distribute_seismic_force_by_height``'s height<=0 rule).
        base_elevation = min(node.z for node in model.nodes.values())
        story_weights: dict[str, StoryWeight] = {}
        story_nodes: dict[str, tuple[int, ...]] = {}
        assigned_nodes: set[int] = set()
        for story_id, story in self.canvas.stories.items():
            nodes_here = self.canvas.nodes_at_story(story_id)
            weight_here = sum(node_weights.get(tag, 0.0) for tag in nodes_here)
            story_weights[story_id] = StoryWeight(
                height=story.elevation - base_elevation, weight=weight_here
            )
            story_nodes[story_id] = nodes_here
            assigned_nodes.update(nodes_here)

        # W (total seismic weight) is the sum of every *story's* own weight,
        # not every node's - a node the Story Manager hasn't assigned to any
        # story (or one sitting exactly at the base) could never receive its
        # own share of the distributed force either way, so counting its
        # weight into W here would inflate the base shear V past what
        # sum(Fx) can actually equal (an equilibrium violation).
        total_weight = sum(story_weight.weight for story_weight in story_weights.values())
        if total_weight <= 0.0:
            self.seismic_result_label.setText(
                "정의된 층에 해당하는 절점에 중량이 없습니다 - Story Manager의 표고가 "
                "실제 절점 위치와 맞는지 확인하세요."
            )
            return
        unassigned_weight = sum(
            weight for tag, weight in node_weights.items() if tag not in assigned_nodes
        )
        unassigned_note = (
            f" (참고: 어느 층에도 속하지 않은 절점의 중량 {unassigned_weight:,.3f}은(는) "
            "W 계산에서 제외되었습니다 - 기초 레벨이거나 Story Manager에 층을 빠뜨렸을 "
            "수 있습니다.)"
            if unassigned_weight > total_weight * 1.0e-6
            else ""
        )

        parameters = SeismicLoadParameters(
            ss=self.seismic_ss.value(),
            s1=self.seismic_s1.value(),
            fa=self.seismic_fa.value(),
            fv=self.seismic_fv.value(),
            r=self.seismic_r.value(),
            ie=self.seismic_ie.value(),
            period=self.seismic_period.value(),
        )
        try:
            cs, base_shear, story_forces = equivalent_lateral_force(
                parameters, total_weight, story_weights
            )
        except ValueError as error:
            self.seismic_result_label.setText(str(error))
            return

        direction_key = str(self.seismic_direction_combo.currentData())
        direction_index = {"x": 0, "y": 1}[direction_key[-1]]
        direction_sign = -1.0 if direction_key.startswith("-") else 1.0
        load_scale = direction_sign * self.seismic_scale_factor.value()
        eccentricity_sign = float(self.seismic_eccentricity_sign.currentData())
        eccentricity = eccentricity_sign * self.seismic_eccentricity.value()
        entries: list[tuple[str, tuple[int, ...], NodalLoadEntry]] = []
        for story_id, force in story_forces.items():
            weight_here = story_weights[story_id].weight
            if weight_here <= 0.0 or force == 0.0:
                continue
            for node_tag in story_nodes[story_id]:
                share = node_weights.get(node_tag, 0.0) / weight_here
                if share <= 0.0:
                    continue
                values = [0.0] * 6
                node_force = force * share * load_scale
                values[direction_index] = node_force
                values[5] = node_force * eccentricity
                payload = NodalLoadEntry(
                    fx=values[0], fy=values[1], fz=values[2], mx=values[3], my=values[4], mz=values[5]
                )
                entries.append(("nodal", (node_tag,), payload))

        applied_count = self.canvas.replace_load_entries_for_case(case_id, entries)
        self.seismic_result_label.setText(
            f"Cs = {cs:.4f}, 밑면전단력 V = {base_shear * load_scale:,.3f} — "
            f"{applied_count}개 절점에 "
            f"'{self.seismic_case_combo.currentText()}' 케이스로 하중을 생성했습니다."
            f"{' 우발편심 Mz를 함께 적용했습니다.' if eccentricity else ''}"
            f"{unassigned_note}"
        )


    def _build_wind_load_generator_page(self) -> QWidget:
        """Readable wind-load specification plus real story-load generation.

        Kz/Gf/Cp remain visible engineer inputs. A separate velocity mode can
        convert 1/2*rho*V0^2 and user-entered modifiers to the model stress
        unit, but is clearly labelled as a reference-pressure conversion,
        not an embedded replacement for the selected KDS edition's tables.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        card, content = self._load_group_card("기본 설정")
        self.wind_code_combo = SafeComboBox()
        self.wind_code_combo.addItem(
            "KDS 41 12 00:2022 — 건축물 설계하중",
            "KDS 41 12 00:2022",
        )
        self.wind_code_combo.addItem("사용자 지정 설계기준", "custom")
        self._add_generator_field(content, "설계기준 (Wind Load Code)", self.wind_code_combo)
        self.wind_description = QLineEdit()
        self.wind_description.setPlaceholderText("예: +X방향 주골조 풍하중")
        self._add_generator_field(content, "설명 (Description)", self.wind_description)
        self.wind_case_combo = SafeComboBox()
        self.wind_case_combo.setToolTip(
            "이 케이스에 이미 있는 하중은 생성할 때마다 계산된 값으로 대체됩니다."
        )
        wind_case_manage_button = QPushButton("관리...")
        wind_case_manage_button.clicked.connect(self._open_load_case_manager)
        self._add_generator_field(
            content,
            "적용할 하중케이스 (Load Case)",
            self._generator_row(self.wind_case_combo, wind_case_manage_button),
            "풍하중 전용 케이스를 권장합니다.",
        )
        layout.addWidget(card)

        pressure_card, pressure = self._load_group_card("기준 속도압")
        hint = QLabel(
            "규준의 지역·지표면조도·지형 조건을 확인한 뒤 직접 설계풍압을 입력하거나, "
            "기본풍속에서 참고 기준속도압을 환산할 수 있습니다."
        )
        hint.setObjectName("loadModeHint")
        hint.setWordWrap(True)
        hint.setMaximumWidth(272)
        pressure.addWidget(hint)
        self.wind_calculation_method = SafeComboBox()
        self.wind_calculation_method.addItem("기준 설계풍압 직접 입력", "direct")
        self.wind_calculation_method.addItem("기본풍속으로 기준속도압 환산", "velocity")
        self._add_generator_field(
            pressure,
            "계산 방식 (Calculation Method)",
            self.wind_calculation_method,
        )
        self.wind_exposure_category = SafeComboBox()
        for category in ("A", "B", "C", "D"):
            self.wind_exposure_category.addItem(f"지표면조도구분 {category}", category)
        self.wind_exposure_category.setCurrentIndex(1)
        self._add_generator_field(
            pressure,
            "지표면조도구분 (Exposure Category)",
            self.wind_exposure_category,
            "층별 노출계수 Kz는 아래 표에 직접 입력합니다.",
        )
        self.wind_q0 = SafeDoubleSpinBox()
        self.wind_q0.setRange(0.0, 1.0e6)
        self.wind_q0.setDecimals(6)
        self.wind_q0.setValue(1.0)
        self.wind_q0_label = self._add_generator_field(
            pressure,
            f"기준 설계풍압 q0 ({self._unit_system.stress})",
            self.wind_q0,
            "층별 설계풍압은 pz = q0 × Kz × Gf × Cp로 계산합니다.",
        )

        self.wind_velocity_inputs = QWidget()
        velocity_layout = QVBoxLayout(self.wind_velocity_inputs)
        velocity_layout.setContentsMargins(0, 0, 0, 0)
        velocity_layout.setSpacing(6)
        self.wind_basic_speed = SafeDoubleSpinBox()
        self.wind_basic_speed.setRange(0.0, 150.0)
        self.wind_basic_speed.setDecimals(2)
        self.wind_basic_speed.setValue(26.0)
        self._add_generator_field(
            velocity_layout,
            "기본풍속 V0 (m/s)",
            self.wind_basic_speed,
        )
        self.wind_air_density = SafeDoubleSpinBox()
        self.wind_air_density.setRange(0.5, 2.0)
        self.wind_air_density.setDecimals(4)
        self.wind_air_density.setValue(1.225)
        self._add_generator_field(
            velocity_layout,
            "공기밀도 ρ (kg/m³)",
            self.wind_air_density,
        )
        self.wind_directionality_factor = SafeDoubleSpinBox()
        self.wind_directionality_factor.setRange(0.0, 3.0)
        self.wind_directionality_factor.setDecimals(3)
        self.wind_directionality_factor.setValue(1.0)
        self._add_generator_field(
            velocity_layout,
            "풍향계수 Kd (Directionality Factor)",
            self.wind_directionality_factor,
        )
        self.wind_topographic_factor = SafeDoubleSpinBox()
        self.wind_topographic_factor.setRange(0.0, 5.0)
        self.wind_topographic_factor.setDecimals(3)
        self.wind_topographic_factor.setValue(1.0)
        self._add_generator_field(
            velocity_layout,
            "지형계수 Kzt (Topographic Factor)",
            self.wind_topographic_factor,
        )
        self.wind_importance_factor = SafeDoubleSpinBox()
        self.wind_importance_factor.setRange(0.0, 3.0)
        self.wind_importance_factor.setDecimals(3)
        self.wind_importance_factor.setValue(1.0)
        self._add_generator_field(
            velocity_layout,
            "풍하중 중요도계수 Iw (Wind Importance Factor)",
            self.wind_importance_factor,
            "환산식 1/2ρV0²에 사용자가 확인한 계수를 곱합니다.",
        )
        pressure.addWidget(self.wind_velocity_inputs)
        self.wind_pressure_summary = QLabel()
        self.wind_pressure_summary.setObjectName("loadDerivedValue")
        self.wind_pressure_summary.setWordWrap(True)
        pressure.addWidget(self.wind_pressure_summary)
        layout.addWidget(pressure_card)

        response_card, response = self._load_group_card("풍하중 계수와 수풍면")
        self.wind_structure_type = SafeComboBox()
        self.wind_structure_type.addItem("강체 구조 (Rigid Structure)", "rigid")
        self.wind_structure_type.addItem("유연 구조 (Flexible Structure)", "flexible")
        self._add_generator_field(
            response,
            "구조물 동적 분류 (Structural Response)",
            self.wind_structure_type,
            "현재 생성기는 입력한 가스트영향계수를 사용합니다.",
        )
        self.wind_gust_factor = SafeDoubleSpinBox()
        self.wind_gust_factor.setRange(0.1, 3.0)
        self.wind_gust_factor.setDecimals(3)
        self.wind_gust_factor.setValue(0.85)
        self._add_generator_field(
            response,
            "가스트영향계수 Gf (Gust Effect Factor)",
            self.wind_gust_factor,
        )
        self.wind_pressure_coefficient = SafeDoubleSpinBox()
        self.wind_pressure_coefficient.setRange(0.0, 5.0)
        self.wind_pressure_coefficient.setDecimals(3)
        self.wind_pressure_coefficient.setValue(1.3)
        self._add_generator_field(
            response,
            "순풍압계수 Cp (Net Pressure Coefficient)",
            self.wind_pressure_coefficient,
            "풍상면과 풍하면 효과를 합성한 값입니다.",
        )
        self.wind_exposed_width = SafeDoubleSpinBox()
        self.wind_exposed_width.setRange(0.0, 1.0e6)
        self.wind_exposed_width.setDecimals(3)
        self.wind_exposed_width_label = self._add_generator_field(
            response,
            f"가력방향 직각 노출 폭 B ({self._unit_system.length})",
            self.wind_exposed_width,
            "층 수풍면적 = B × 층 분담높이로 계산합니다.",
        )
        layout.addWidget(response_card)

        direction_card, direction = self._load_group_card("가력 방향과 층별 노출계수")
        self.wind_direction_combo = SafeComboBox()
        for label, key in (
            ("전역 +X 방향", "x"),
            ("전역 -X 방향", "-x"),
            ("전역 +Y 방향", "y"),
            ("전역 -Y 방향", "-y"),
        ):
            self.wind_direction_combo.addItem(label, key)
        self._add_generator_field(
            direction,
            "풍하중 방향 (Loading Direction)",
            self.wind_direction_combo,
        )
        self.wind_scale_factor = SafeDoubleSpinBox()
        self.wind_scale_factor.setRange(0.0, 100.0)
        self.wind_scale_factor.setDecimals(3)
        self.wind_scale_factor.setValue(1.0)
        self._add_generator_field(
            direction,
            "방향 배율 (Direction Scale Factor)",
            self.wind_scale_factor,
        )
        kz_label = QLabel("층별 노출계수 Kz (Exposure Coefficient by Story)")
        kz_label.setObjectName("loadParameterLabel")
        kz_label.setWordWrap(True)
        direction.addWidget(kz_label)
        self.wind_kz_table = QTableWidget(0, 2)
        self.wind_kz_table.setHorizontalHeaderLabels(["층", "노출계수 Kz"])
        self.wind_kz_table.verticalHeader().setVisible(False)
        self.wind_kz_table.horizontalHeader().setStretchLastSection(True)
        self.wind_kz_table.setMaximumWidth(272)
        self.wind_kz_table.setMaximumHeight(140)
        direction.addWidget(self.wind_kz_table)
        self.canvas.story_state_changed.connect(self._refresh_wind_kz_table)
        self._refresh_wind_kz_table()
        layout.addWidget(direction_card)

        self.canvas.load_state_changed.connect(self._refresh_wind_case_combo)
        self._refresh_wind_case_combo()

        generate_button = QPushButton("풍하중 생성")
        generate_button.setObjectName("loadPrimaryButton")
        generate_button.clicked.connect(self._generate_wind_load)
        layout.addWidget(generate_button)

        self.wind_result_label = QLabel()
        self.wind_result_label.setWordWrap(True)
        self.wind_result_label.setObjectName("loadModeHint")
        layout.addWidget(self.wind_result_label)

        self.wind_calculation_method.currentIndexChanged.connect(
            self._on_wind_calculation_method_changed
        )
        for field in (
            self.wind_q0,
            self.wind_basic_speed,
            self.wind_air_density,
            self.wind_directionality_factor,
            self.wind_topographic_factor,
            self.wind_importance_factor,
            self.wind_gust_factor,
            self.wind_pressure_coefficient,
            self.wind_scale_factor,
        ):
            field.valueChanged.connect(self._refresh_wind_parameter_summary)
        self._on_wind_calculation_method_changed()

        layout.addStretch(1)
        return page


    def _on_wind_calculation_method_changed(self, _index: int | None = None) -> None:
        velocity_mode = self.wind_calculation_method.currentData() == "velocity"
        self.wind_velocity_inputs.setVisible(velocity_mode)
        self.wind_q0.setReadOnly(velocity_mode)
        self._refresh_wind_parameter_summary()


    def _refresh_wind_parameter_summary(self, _value: object | None = None) -> None:
        if not hasattr(self, "wind_pressure_summary"):
            return
        if self.wind_calculation_method.currentData() == "velocity":
            pressure_pa = (
                0.5
                * self.wind_air_density.value()
                * self.wind_basic_speed.value() ** 2
                * self.wind_directionality_factor.value()
                * self.wind_topographic_factor.value()
                * self.wind_importance_factor.value()
            )
            pressure_model = mpa_to_stress_unit(
                pressure_pa / 1.0e6,
                self._unit_system.force,
                self._unit_system.length,
            )
            self.wind_q0.blockSignals(True)
            self.wind_q0.setValue(pressure_model)
            self.wind_q0.blockSignals(False)
        design_pressure = (
            self.wind_q0.value()
            * self.wind_gust_factor.value()
            * self.wind_pressure_coefficient.value()
        )
        self.wind_pressure_summary.setText(
            f"자동 계산 · Kz=1.0 기준 풍압 p = {design_pressure:.4f} "
            f"{self._unit_system.stress}\n"
            "실제 층별 값은 이 풍압에 각 층 Kz를 곱합니다."
        )


    def _load_generator_settings(self) -> dict[str, object]:
        """Persist generator specifications, not only their generated loads."""
        story_kz: dict[str, float] = {}
        for row in range(self.wind_kz_table.rowCount()):
            name_item = self.wind_kz_table.item(row, 0)
            kz_item = self.wind_kz_table.item(row, 1)
            if name_item is None or kz_item is None:
                continue
            try:
                story_kz[str(name_item.data(Qt.ItemDataRole.UserRole))] = float(
                    kz_item.text()
                )
            except ValueError:
                continue
        return {
            "wind": {
                "code": self.wind_code_combo.currentData(),
                "description": self.wind_description.text(),
                "case_id": self.wind_case_combo.currentData(),
                "method": self.wind_calculation_method.currentData(),
                "exposure_category": self.wind_exposure_category.currentData(),
                "reference_pressure": self.wind_q0.value(),
                "basic_speed": self.wind_basic_speed.value(),
                "air_density": self.wind_air_density.value(),
                "directionality_factor": self.wind_directionality_factor.value(),
                "topographic_factor": self.wind_topographic_factor.value(),
                "importance_factor": self.wind_importance_factor.value(),
                "structure_type": self.wind_structure_type.currentData(),
                "gust_factor": self.wind_gust_factor.value(),
                "pressure_coefficient": self.wind_pressure_coefficient.value(),
                "exposed_width": self.wind_exposed_width.value(),
                "direction": self.wind_direction_combo.currentData(),
                "scale_factor": self.wind_scale_factor.value(),
                "story_kz": story_kz,
            },
            "seismic": {
                "code": self.seismic_code_combo.currentData(),
                "description": self.seismic_description.text(),
                "case_id": self.seismic_case_combo.currentData(),
                "site_class": self.seismic_site_class.currentData(),
                "ss": self.seismic_ss.value(),
                "s1": self.seismic_s1.value(),
                "fa": self.seismic_fa.value(),
                "fv": self.seismic_fv.value(),
                "system_description": self.seismic_system_description.text(),
                "r": self.seismic_r.value(),
                "ie": self.seismic_ie.value(),
                "period_method": self.seismic_period_method.currentData(),
                "period": self.seismic_period.value(),
                "direction": self.seismic_direction_combo.currentData(),
                "scale_factor": self.seismic_scale_factor.value(),
                "eccentricity_sign": self.seismic_eccentricity_sign.currentData(),
                "eccentricity": self.seismic_eccentricity.value(),
            },
        }

    @staticmethod
    def _restore_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)


    def _restore_load_generator_settings(self, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        wind = raw.get("wind")
        if isinstance(wind, dict):
            for combo, key in (
                (self.wind_code_combo, "code"),
                (self.wind_exposure_category, "exposure_category"),
                (self.wind_structure_type, "structure_type"),
                (self.wind_direction_combo, "direction"),
            ):
                self._restore_combo_data(combo, wind.get(key))
            self.wind_description.setText(str(wind.get("description", "")))
            for field, key in (
                (self.wind_q0, "reference_pressure"),
                (self.wind_basic_speed, "basic_speed"),
                (self.wind_air_density, "air_density"),
                (self.wind_directionality_factor, "directionality_factor"),
                (self.wind_topographic_factor, "topographic_factor"),
                (self.wind_importance_factor, "importance_factor"),
                (self.wind_gust_factor, "gust_factor"),
                (self.wind_pressure_coefficient, "pressure_coefficient"),
                (self.wind_exposed_width, "exposed_width"),
                (self.wind_scale_factor, "scale_factor"),
            ):
                if key in wind:
                    field.setValue(float(wind[key]))
            self._restore_combo_data(
                self.wind_calculation_method, wind.get("method", "direct")
            )
            self._refresh_wind_kz_table()
            story_kz = wind.get("story_kz")
            if isinstance(story_kz, dict):
                for row in range(self.wind_kz_table.rowCount()):
                    name_item = self.wind_kz_table.item(row, 0)
                    if name_item is None:
                        continue
                    story_id = str(name_item.data(Qt.ItemDataRole.UserRole))
                    if story_id in story_kz:
                        self.wind_kz_table.item(row, 1).setText(str(story_kz[story_id]))
            self._refresh_wind_case_combo()
            self._restore_combo_data(self.wind_case_combo, wind.get("case_id"))
            self._on_wind_calculation_method_changed()

        seismic = raw.get("seismic")
        if isinstance(seismic, dict):
            for combo, key in (
                (self.seismic_code_combo, "code"),
                (self.seismic_site_class, "site_class"),
                (self.seismic_period_method, "period_method"),
                (self.seismic_direction_combo, "direction"),
                (self.seismic_eccentricity_sign, "eccentricity_sign"),
            ):
                self._restore_combo_data(combo, seismic.get(key))
            self.seismic_description.setText(str(seismic.get("description", "")))
            self.seismic_system_description.setText(
                str(seismic.get("system_description", ""))
            )
            for field, key in (
                (self.seismic_ss, "ss"),
                (self.seismic_s1, "s1"),
                (self.seismic_fa, "fa"),
                (self.seismic_fv, "fv"),
                (self.seismic_r, "r"),
                (self.seismic_ie, "ie"),
                (self.seismic_period, "period"),
                (self.seismic_scale_factor, "scale_factor"),
                (self.seismic_eccentricity, "eccentricity"),
            ):
                if key in seismic:
                    field.setValue(float(seismic[key]))
            self._refresh_seismic_case_combo()
            self._restore_combo_data(self.seismic_case_combo, seismic.get("case_id"))
            self._refresh_seismic_parameter_summary()


    def _refresh_wind_kz_table(self) -> None:
        if not hasattr(self, "wind_kz_table"):
            return
        previous_kz: dict[str, str] = {}
        for row in range(self.wind_kz_table.rowCount()):
            name_item = self.wind_kz_table.item(row, 0)
            kz_item = self.wind_kz_table.item(row, 1)
            if name_item is not None and kz_item is not None:
                previous_kz[name_item.data(Qt.ItemDataRole.UserRole)] = kz_item.text()
        stories = sorted(
            self.canvas.stories.values(), key=lambda story: story.elevation, reverse=True
        )
        self.wind_kz_table.setRowCount(len(stories))
        for row, story in enumerate(stories):
            name_item = QTableWidgetItem(story.name)
            name_item.setData(Qt.ItemDataRole.UserRole, story.id)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.wind_kz_table.setItem(row, 0, name_item)
            kz_item = QTableWidgetItem(previous_kz.get(story.id, "1.0"))
            self.wind_kz_table.setItem(row, 1, kz_item)


    def _refresh_wind_case_combo(self) -> None:
        if not hasattr(self, "wind_case_combo"):
            return
        combo = self.wind_case_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for case in self.canvas.load_cases.values():
            combo.addItem(case.name, case.id)
        index = combo.findData(previous)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)


    def _generate_wind_load(self) -> None:
        case_id = self.wind_case_combo.currentData()
        if not case_id:
            self.wind_result_label.setText(
                "먼저 '케이스 관리...'에서 풍하중을 담을 하중케이스를 만드세요."
            )
            return
        if not self.canvas.stories:
            self.wind_result_label.setText(
                "Story Manager에서 층을 먼저 정의해야 층별로 힘을 분배할 수 있습니다."
            )
            return
        if self.wind_exposed_width.value() <= 0.0:
            self.wind_result_label.setText("노출 폭(B)을 0보다 크게 입력하세요.")
            return

        story_kz: dict[str, float] = {}
        for row in range(self.wind_kz_table.rowCount()):
            name_item = self.wind_kz_table.item(row, 0)
            kz_item = self.wind_kz_table.item(row, 1)
            if name_item is None or kz_item is None:
                continue
            try:
                story_kz[name_item.data(Qt.ItemDataRole.UserRole)] = float(kz_item.text())
            except ValueError:
                self.wind_result_label.setText(
                    f"'{name_item.text()}' 층의 Kz 값이 숫자가 아닙니다."
                )
                return
        story_elevations = {
            story_id: story.elevation for story_id, story in self.canvas.stories.items()
        }

        parameters = WindLoadParameters(
            reference_pressure=self.wind_q0.value(),
            gust_factor=self.wind_gust_factor.value(),
            pressure_coefficient=self.wind_pressure_coefficient.value(),
            exposed_width=self.wind_exposed_width.value(),
        )
        story_forces = wind_force_by_story(parameters, story_kz, story_elevations)

        direction_key = str(self.wind_direction_combo.currentData())
        direction_index = {"x": 0, "y": 1}[direction_key[-1]]
        direction_sign = -1.0 if direction_key.startswith("-") else 1.0
        load_scale = direction_sign * self.wind_scale_factor.value()
        entries: list[tuple[str, tuple[int, ...], NodalLoadEntry]] = []
        for story_id, force in story_forces.items():
            if force == 0.0:
                continue
            nodes_here = self.canvas.nodes_at_story(story_id)
            if not nodes_here:
                continue
            share = force * load_scale / len(nodes_here)
            for node_tag in nodes_here:
                values = [0.0] * 6
                values[direction_index] = share
                payload = NodalLoadEntry(
                    fx=values[0], fy=values[1], fz=values[2], mx=values[3], my=values[4], mz=values[5]
                )
                entries.append(("nodal", (node_tag,), payload))

        applied_count = self.canvas.replace_load_entries_for_case(case_id, entries)
        total_force = sum(story_forces.values()) * load_scale
        self.wind_result_label.setText(
            f"총 풍하중 = {total_force:,.3f} — {applied_count}개 절점에 "
            f"'{self.wind_case_combo.currentText()}' 케이스로 하중을 생성했습니다 "
            "(같은 층의 절점에 균등 분배)."
        )


    def _build_load_case_command_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        card, content = self._load_group_card("하중케이스 정의")
        hint = QLabel("고정하중, 활하중, 풍하중처럼 하중을 구분할 케이스를 정의합니다.")
        hint.setObjectName("loadModeHint")
        hint.setWordWrap(True)
        content.addWidget(hint)
        button = QPushButton("하중케이스 관리 열기")
        button.setObjectName("loadPrimaryButton")
        button.clicked.connect(self._open_load_case_manager)
        content.addWidget(button)
        layout.addWidget(card)
        layout.addStretch(1)
        return page


    def _build_load_combination_command_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        card, content = self._load_group_card("하중조합")
        hint = QLabel("하중케이스별 계수를 정의해 조합을 만들고 3D 화면에서 확인합니다.")
        hint.setObjectName("loadModeHint")
        hint.setWordWrap(True)
        content.addWidget(hint)
        row = QHBoxLayout()
        self.load_combination_combo = QComboBox()
        self.load_combination_combo.currentIndexChanged.connect(
            self._on_load_combination_combo_changed
        )
        row.addWidget(self.load_combination_combo, 1)
        edit = QPushButton("편집")
        edit.clicked.connect(self._open_load_combination_manager)
        row.addWidget(edit)
        content.addLayout(row)
        self.canvas.load_state_changed.connect(self._refresh_load_combination_combo)
        self._refresh_load_combination_combo()
        layout.addWidget(card)
        layout.addStretch(1)
        return page


    def _build_make_load_case_command_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        source_card, source = self._load_group_card("원본과 새 케이스")
        hint = QLabel(
            "선택한 조합의 계수를 실제 하중 데이터에 곱해 하나의 새 정적 하중케이스로 만듭니다."
        )
        hint.setObjectName("loadModeHint")
        hint.setWordWrap(True)
        source.addWidget(hint)
        form = QFormLayout()
        self.make_load_combination_combo = QComboBox()
        form.addRow("원본 조합", self.make_load_combination_combo)
        self.make_load_case_name = QLineEdit()
        self.make_load_case_name.setPlaceholderText("예: ULS_APPLIED")
        form.addRow("새 하중케이스", self.make_load_case_name)
        source.addLayout(form)
        layout.addWidget(source_card)

        include_card, include = self._load_group_card("포함할 하중")
        self.make_load_nodal = QCheckBox("Nodal Load")
        self.make_load_member = QCheckBox("Member Load")
        self.make_load_floor = QCheckBox("Floor Load")
        self.make_load_self_weight = QCheckBox("Self Weight")
        for checkbox in (
            self.make_load_nodal,
            self.make_load_member,
            self.make_load_floor,
            self.make_load_self_weight,
        ):
            checkbox.setChecked(True)
            include.addWidget(checkbox)
        layout.addWidget(include_card)

        option_card, options = self._load_group_card("생성 옵션")
        self.make_load_replace_existing = QCheckBox("같은 이름의 기존 하중을 교체")
        options.addWidget(self.make_load_replace_existing)
        self.make_load_activate_analysis = QCheckBox("생성 후 지원 하중을 해석 모델에 가력")
        self.make_load_activate_analysis.setChecked(True)
        self.make_load_activate_analysis.setToolTip(
            "절점하중과 전체-span 부재 균등/선형분포하중을 현재 해석 하중으로 교체합니다."
        )
        options.addWidget(self.make_load_activate_analysis)
        layout.addWidget(option_card)
        self.make_load_status = QLabel()
        self.make_load_status.setObjectName("setupSectionHint")
        self.make_load_status.setWordWrap(True)
        layout.addWidget(self.make_load_status)
        self.make_load_create_button = QPushButton("하중케이스 생성")
        self.make_load_create_button.setObjectName("loadPrimaryButton")
        self.make_load_create_button.clicked.connect(self._make_load_case_from_combination)
        layout.addWidget(self.make_load_create_button)
        self._refresh_load_combination_combo()
        layout.addStretch(1)
        return page


    def _on_load_command_changed(self, _index: int | None = None) -> None:
        key = str(self.load_command_combo.currentData())
        if key == "load_cases":
            self.load_category_stack.setCurrentIndex(self.load_category_pages["definitions"])
            return
        if key in {"wind", "seismic"}:
            self.load_category_stack.setCurrentIndex(self.load_category_pages["generators"])
            generator_index = self.load_generators_subnav_combo.findData(key)
            if generator_index >= 0:
                self.load_generators_subnav_combo.setCurrentIndex(generator_index)
            return
        if key in {"load_combinations", "make_combination"}:
            self.load_category_stack.setCurrentIndex(self.load_category_pages["combinations"])
            combination_index = self.load_combinations_subnav_combo.findData(key)
            if combination_index >= 0:
                self.load_combinations_subnav_combo.setCurrentIndex(combination_index)
            return

        self.load_category_stack.setCurrentIndex(self.load_category_pages["direct"])
        if key in {"nodal", "member_uniform", "member_linear"}:
            self.load_command_stack.setCurrentIndex(self.load_command_pages["quick"])
            target_id = {"nodal": 0, "member_uniform": 1, "member_linear": 2}[key]
            self.load_target_group.button(target_id).setChecked(True)
            self._load_target_changed()
            self.load_command_form_title.setText(
                {
                    "nodal": "Nodal Load",
                    "member_uniform": "Mem Uniform",
                    "member_linear": "Mem Linear",
                }[key]
            )
            self._on_load_apply_mode_changed()
            return
        self.load_command_stack.setCurrentIndex(self.load_command_pages["entry"])
        top_kind = "member" if key.startswith("member_") else key
        type_index = self.load3d_type_combo.findData(top_kind)
        if type_index >= 0:
            self.load3d_type_combo.setCurrentIndex(type_index)
        subtype_index = self.load3d_member_subtype_combo.findData(key)
        if subtype_index >= 0:
            self.load3d_member_subtype_combo.setCurrentIndex(subtype_index)
        self.load3d_command_title.setText(
            {
                "self_weight": "Self Weight",
                "member_point": "Mem Point",
                "member_partial": "Mem Partial",
                "member_moment": "Mem Moment",
                "floor": "Floor Load",
            }.get(key, "Load Settings")
        )
        self._on_load_apply_mode_changed()


    def _make_load_case_from_combination(self) -> None:
        combination_name = self.make_load_combination_combo.currentData()
        case_name = self.make_load_case_name.text().strip()
        selected_groups = {
            group
            for group, checkbox in (
                ("nodal", self.make_load_nodal),
                ("member", self.make_load_member),
                ("floor", self.make_load_floor),
                ("self_weight", self.make_load_self_weight),
            )
            if checkbox.isChecked()
        }
        if not combination_name:
            self.make_load_status.setText("⚠ 먼저 원본 하중조합을 선택하세요.")
            return
        if not case_name:
            self.make_load_status.setText("⚠ 새 하중케이스 이름을 입력하세요.")
            return
        count = self.canvas.create_load_case_from_combination(
            str(combination_name),
            case_name,
            replace_existing=self.make_load_replace_existing.isChecked(),
            selected_groups=selected_groups,
            activate_for_analysis=self.make_load_activate_analysis.isChecked(),
        )
        if count is None:
            self.make_load_status.setText("⚠ 같은 이름의 하중케이스가 이미 있습니다.")
            return
        suffix = (
            " · 지원되는 하중을 해석 모델에 가력했습니다."
            if self.make_load_activate_analysis.isChecked()
            else ""
        )
        self.make_load_status.setText(f"✓ {case_name}에 하중 {count}개를 생성했습니다{suffix}")


    def _build_3d_load_manager_content(self) -> QWidget:
        """Case-based settings host selected by the Loads command picker."""
        section = QWidget()
        root = QVBoxLayout(section)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self._editing_load_entry_id: int | None = None

        self.load3d_command_title = QLabel("Load Settings")
        self.load3d_command_title.setObjectName("loadCommandTitle")
        root.addWidget(self.load3d_command_title)

        # Internal selectors are driven by the command list above. They stay
        # as real combo boxes so edit/reselect code can reuse the same state
        # transitions without exposing a second load-type chooser.
        self.load3d_type_combo = QComboBox()
        for key, label in (
            ("nodal", "Nodal Load"),
            ("member", "Member Load"),
            ("floor", "Floor Load"),
            ("self_weight", "Self Weight"),
        ):
            self.load3d_type_combo.addItem(label, key)
        self.load3d_type_combo.currentIndexChanged.connect(self._on_load3d_type_changed)

        self.load3d_member_subtype_row = QWidget()
        subtype_layout = QFormLayout(self.load3d_member_subtype_row)
        subtype_layout.setContentsMargins(0, 0, 0, 0)
        self.load3d_member_subtype_combo = QComboBox()
        for key, label in (
            ("member_point", "Point Load"),
            ("member_uniform", "Uniform Distributed"),
            ("member_linear", "Linear Varying"),
            ("member_partial", "Partial Distributed"),
            ("member_moment", "Point Moment"),
        ):
            self.load3d_member_subtype_combo.addItem(label, key)
        subtype_layout.addRow("부재하중 형식", self.load3d_member_subtype_combo)
        self.load3d_member_subtype_combo.currentIndexChanged.connect(
            self._on_load3d_member_subtype_changed
        )

        self.load3d_form_stack = _CurrentPageOnlyStack()
        self.load3d_form_pages = {
            "nodal": self.load3d_form_stack.addWidget(self._build_load3d_nodal_form()),
            "member": self.load3d_form_stack.addWidget(self._build_load3d_member_form()),
            "floor": self.load3d_form_stack.addWidget(self._build_load3d_floor_form()),
            "self_weight": self.load3d_form_stack.addWidget(self._build_load3d_self_weight_form()),
        }
        root.addWidget(self.load3d_form_stack)

        self.load3d_target_count_label = QLabel()
        self.load3d_target_count_label.setObjectName("setupSectionHint")
        root.addWidget(self.load3d_target_count_label)
        self.canvas.selection_changed.connect(self._refresh_load3d_target_count)

        self.load3d_status_label = QLabel()
        self.load3d_status_label.setObjectName("setupSectionHint")
        self.load3d_status_label.setWordWrap(True)
        root.addWidget(self.load3d_status_label)

        self.load3d_apply_button = QPushButton("적용")
        self.load3d_apply_button.setObjectName("loadPrimaryButton")
        self.load3d_apply_button.clicked.connect(self._apply_load3d)
        root.addWidget(self.load3d_apply_button)
        root.addStretch(1)

        self.load3d_type_combo.setCurrentIndex(0)
        self._on_load3d_type_changed()
        self.load3d_member_subtype_combo.setCurrentIndex(0)
        self._on_load3d_member_subtype_changed()
        self._refresh_load3d_target_count()
        return section


    def _build_load3d_nodal_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.load3d_nodal_coord = QComboBox()
        self.load3d_nodal_coord.addItem("전역 좌표계", "global")
        self.load3d_nodal_coord.addItem("로컬 좌표계", "local")
        form.addRow("좌표계", self.load3d_nodal_coord)
        self.load3d_nodal_fields: dict[str, QDoubleSpinBox] = {}
        self.load3d_nodal_field_labels: dict[str, QLabel] = {}
        for key, label in (("fx", "Fx"), ("fy", "Fy"), ("fz", "Fz"), ("mx", "Mx"), ("my", "My"), ("mz", "Mz")):
            spin = self._number(0.0)
            self.load3d_nodal_fields[key] = spin
            label_widget = QLabel(label)
            self.load3d_nodal_field_labels[key] = label_widget
            form.addRow(label_widget, spin)
        return widget


    def _build_load3d_member_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self._load3d_member_form = form
        self.load3d_member_coord = QComboBox()
        self.load3d_member_coord.addItem("전역 좌표계", "global")
        self.load3d_member_coord.addItem("로컬 좌표계", "local")
        form.addRow("좌표계", self.load3d_member_coord)
        self.load3d_member_direction = QComboBox()
        self.load3d_member_direction.addItems(["X", "Y", "Z"])
        self.load3d_member_direction.setCurrentText("Y")
        form.addRow("방향", self.load3d_member_direction)
        self.load3d_member_start_value = self._number(0.0)
        self.load3d_member_start_value_label = QLabel("시작값")
        form.addRow(self.load3d_member_start_value_label, self.load3d_member_start_value)
        self.load3d_member_end_value = self._number(0.0)
        self.load3d_member_end_value_label = QLabel("끝값")
        form.addRow(self.load3d_member_end_value_label, self.load3d_member_end_value)
        self.load3d_member_start_position = self._number(0.0)
        form.addRow("시작 위치", self.load3d_member_start_position)
        self.load3d_member_end_position = self._number(1.0)
        form.addRow("끝 위치", self.load3d_member_end_position)
        self.load3d_member_position_unit = QComboBox()
        self.load3d_member_position_unit.addItem("비율 (0~1)", "ratio")
        self.load3d_member_position_unit.addItem("길이", "length")
        form.addRow("위치 기준", self.load3d_member_position_unit)
        return widget


    def _build_load3d_floor_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        # MIDAS-style click-to-place alternative to the ordinary rubber-band/
        # ctrl-click node selection above: "노드 클릭으로 지정" enters
        # floor_pick mode (cursor becomes CrossCursor via the existing 3D
        # picking-mode sync, same as plain select), 완료 commits the
        # boundary in click order once >= 3 distinct nodes are picked (see
        # canvas_load_entries.py's begin/add/finish/cancel_floor_picking),
        # 취소 discards it. The existing "선택된 경계 노드 수" status label
        # below already updates live for this too, since add_floor_boundary_
        # node emits selection_changed the same way plain node-picking does.
        pick_row = QHBoxLayout()
        self.load3d_floor_pick_start_button = QPushButton("노드 클릭으로 지정")
        self.load3d_floor_pick_start_button.clicked.connect(self._start_floor_boundary_picking)
        pick_row.addWidget(self.load3d_floor_pick_start_button)
        self.load3d_floor_pick_finish_button = QPushButton("완료")
        self.load3d_floor_pick_finish_button.setEnabled(False)
        self.load3d_floor_pick_finish_button.clicked.connect(self._finish_floor_boundary_picking)
        self.load3d_floor_pick_finish_button.hide()
        pick_row.addWidget(self.load3d_floor_pick_finish_button)
        self.load3d_floor_pick_cancel_button = QPushButton("취소")
        self.load3d_floor_pick_cancel_button.clicked.connect(self._cancel_floor_boundary_picking)
        self.load3d_floor_pick_cancel_button.hide()
        pick_row.addWidget(self.load3d_floor_pick_cancel_button)
        form.addRow(pick_row)

        type_row = QHBoxLayout()
        self.load3d_floor_type_combo = QComboBox()
        self.load3d_floor_type_combo.addItem("(직접 입력)", None)
        type_row.addWidget(self.load3d_floor_type_combo, 1)
        type_manage_button = QPushButton("...")
        type_manage_button.setObjectName("loadEllipsisButton")
        type_manage_button.setToolTip("Floor Load Type 관리")
        type_manage_button.clicked.connect(self._open_floor_load_type_manager)
        type_row.addWidget(type_manage_button)
        form.addRow("Floor Load Type", type_row)
        self.load3d_floor_type_apply_button = QPushButton("타입 일괄 적용")
        self.load3d_floor_type_apply_button.setToolTip(
            "타입에 등록된 케이스(콘크리트 자중, 바닥재 자중, 활하중처럼)마다 "
            "하중을 하나씩 만들어 선택한 경계 절점에 동시에 적용합니다."
        )
        self.load3d_floor_type_apply_button.clicked.connect(self._apply_floor_load_type)
        form.addRow(self.load3d_floor_type_apply_button)
        self.canvas.load_state_changed.connect(self._refresh_floor_load_type_combo)
        self._refresh_floor_load_type_combo()

        self.load3d_floor_magnitude = self._number(0.0)
        self.load3d_floor_magnitude_label = QLabel()
        form.addRow(self.load3d_floor_magnitude_label, self.load3d_floor_magnitude)
        self.load3d_floor_direction = QComboBox()
        for value, label in (("-z", "-Z"), ("+z", "+Z"), ("-x", "-X"), ("+x", "+X"), ("-y", "-Y"), ("+y", "+Y")):
            self.load3d_floor_direction.addItem(label, value)
        form.addRow("방향", self.load3d_floor_direction)
        self.load3d_floor_distribution = QComboBox()
        self.load3d_floor_distribution.addItem("1방향", "one_way")
        self.load3d_floor_distribution.addItem("2방향 (준비 중)", "two_way")
        form.addRow("분배 방식", self.load3d_floor_distribution)
        self.load3d_floor_span_direction = QComboBox()
        self.load3d_floor_span_direction.addItem("X", "x")
        self.load3d_floor_span_direction.addItem("Y", "y")
        form.addRow("주방향", self.load3d_floor_span_direction)
        self.load3d_floor_preview_button = QPushButton("분배 미리보기 (준비 중)")
        self.load3d_floor_preview_button.setEnabled(False)
        form.addRow(self.load3d_floor_preview_button)
        return widget


    def _build_load3d_self_weight_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.load3d_self_weight_case = QLabel()
        form.addRow("하중케이스", self.load3d_self_weight_case)
        self.canvas.load_state_changed.connect(self._refresh_load3d_self_weight_case_label)
        self.load3d_self_weight_fx = self._number(0.0)
        form.addRow("X 계수", self.load3d_self_weight_fx)
        self.load3d_self_weight_fy = self._number(0.0)
        form.addRow("Y 계수", self.load3d_self_weight_fy)
        self.load3d_self_weight_fz = self._number(-1.0)
        form.addRow("Z 계수", self.load3d_self_weight_fz)
        self.load3d_self_weight_apply_all = QCheckBox("전체 부재에 적용")
        self.load3d_self_weight_apply_all.setChecked(True)
        form.addRow(self.load3d_self_weight_apply_all)
        return widget


    def _refresh_load3d_self_weight_case_label(self) -> None:
        if not hasattr(self, "load3d_self_weight_case"):
            return
        case = self.canvas.load_cases.get(self.canvas.active_load_case_id)
        self.load3d_self_weight_case.setText(case.name if case is not None else "—")


    def _on_load3d_type_changed(self, _index: int | None = None) -> None:
        key = self.load3d_type_combo.currentData()
        self.load3d_member_subtype_row.setVisible(key == "member")
        self.load3d_form_stack.setCurrentIndex(self.load3d_form_pages[key])
        if key == "self_weight":
            self._refresh_load3d_self_weight_case_label()
        self._refresh_load3d_target_count()


    def _on_load3d_member_subtype_changed(self, _index: int | None = None) -> None:
        key = self.load3d_member_subtype_combo.currentData()
        is_point = key in ("member_point", "member_moment")
        form = self._load3d_member_form
        form.setRowVisible(self.load3d_member_end_value, not is_point)
        is_partial = key == "member_partial"
        form.setRowVisible(self.load3d_member_start_position, is_point or is_partial)
        form.setRowVisible(self.load3d_member_end_position, is_partial)
        form.setRowVisible(self.load3d_member_position_unit, is_point or is_partial)
        self._refresh_load3d_unit_labels()


    def _refresh_support_spring_unit_labels(self) -> None:
        """Translational spring stiffness is force/length; rotational is
        moment/radian, which is just ``moment`` since a radian is
        dimensionless - see the custom support row's own spring fields."""
        if not hasattr(self, "support_spring_field_labels"):
            return
        for dof, label_widget in self.support_spring_field_labels.items():
            unit = self._unit_system.moment if dof.startswith("R") else self._unit_system.force_per_length
            label_widget.setText(f"{dof} ({unit})")
            self.support_spring_fields[dof].setToolTip(f"{dof} 방향 스프링 강성 ({unit})")


    def _refresh_load3d_unit_labels(self) -> None:
        """Every unit-bearing label in the Loads tab's case-based forms
        (nodal/member/floor), rebuilt from the live ``self._unit_system`` -
        called on unit-system change and whenever the member subtype changes
        (a member load's own unit depends on whether it is a point force,
        a point moment, or a distributed load intensity)."""
        if not hasattr(self, "load3d_nodal_field_labels"):
            return
        for key, label_widget in self.load3d_nodal_field_labels.items():
            base = key.capitalize()
            unit = self._unit_system.moment if key.startswith("m") else self._unit_system.force
            label_widget.setText(f"{base} ({unit})")
        member_subtype = self.load3d_member_subtype_combo.currentData()
        if member_subtype == "member_moment":
            member_unit = self._unit_system.moment
        elif member_subtype == "member_point":
            member_unit = self._unit_system.force
        else:
            member_unit = self._unit_system.force_per_length
        self.load3d_member_start_value_label.setText(f"시작값 ({member_unit})")
        self.load3d_member_end_value_label.setText(f"끝값 ({member_unit})")
        self.load3d_floor_magnitude_label.setText(f"크기 ({self._unit_system.stress})")
        if hasattr(self, "wind_q0_label"):
            self.wind_q0_label.setText(
                f"기준 설계풍압 q0 ({self._unit_system.stress})"
            )
            self.wind_exposed_width_label.setText(
                f"가력방향 직각 노출 폭 B ({self._unit_system.length})"
            )
            self.seismic_eccentricity_label.setText(
                f"편심거리 e ({self._unit_system.length})"
            )
            self._refresh_wind_parameter_summary()


    def _current_load3d_top_kind(self) -> str:
        return str(self.load3d_type_combo.currentData())


    def _current_load3d_member_subtype(self) -> str:
        return str(self.load3d_member_subtype_combo.currentData())


    def _refresh_load3d_target_count(self) -> None:
        if not hasattr(self, "load3d_target_count_label"):
            return
        kind = self._current_load3d_top_kind()
        if kind == "nodal":
            self.load3d_target_count_label.setText(f"선택된 절점 수: {len(self.canvas.selected_nodes)}")
        elif kind == "member":
            self.load3d_target_count_label.setText(f"선택된 부재 수: {len(self.canvas.selected_elements)}")
        elif kind == "floor":
            if self.canvas.mode == "floor_pick":
                count = len(self.canvas._floor_chain)
                self.load3d_target_count_label.setText(
                    f"선택 {count}개 / 최소 3개" if count < 3 else f"선택 {count}개 / 완료 가능"
                )
                self.load3d_floor_pick_finish_button.setEnabled(count >= 3)
            else:
                self.load3d_target_count_label.setText(
                    f"선택된 경계 노드 수: {len(self.canvas.selected_nodes)} (3개 이상 필요)"
                )
        elif kind == "self_weight":
            if self.load3d_self_weight_apply_all.isChecked():
                self.load3d_target_count_label.setText("전체 부재에 적용됩니다.")
            else:
                self.load3d_target_count_label.setText(f"선택된 부재 수: {len(self.canvas.selected_elements)}")


    def _start_floor_boundary_picking(self) -> None:
        self.canvas.begin_floor_picking()
        self._set_mode(
            "floor_pick",
            "바닥하중 경계 노드를 순서대로 클릭하세요 (3개 이상, 완료로 확정).",
        )
        self.load3d_floor_pick_start_button.hide()
        self.load3d_floor_pick_finish_button.show()
        self.load3d_floor_pick_cancel_button.show()
        self._refresh_load3d_target_count()


    def _reset_floor_boundary_picking_ui(self) -> None:
        """Shared by 완료/취소/Esc - always returns the panel to the same
        resting state regardless of which of the three ended the pick."""
        self.load3d_floor_pick_start_button.show()
        self.load3d_floor_pick_finish_button.hide()
        self.load3d_floor_pick_finish_button.setEnabled(False)
        self.load3d_floor_pick_cancel_button.hide()
        self._set_mode(
            "select",
            "선택 · 클릭 또는 드래그로 선택하고 캔버스 위쪽 막대에서 속성을 적용합니다.",
        )
        self._refresh_load3d_target_count()


    def _finish_floor_boundary_picking(self) -> None:
        # Shared by the 완료 button and _on_3d_node_picked's own auto-close
        # (re-clicking the boundary's first node once >= 3 are picked) - both
        # paths mean "the boundary is done, commit it".
        #
        # Checked before consuming the chain (matches _apply_load3d's own
        # case_id-first order) - a missing Load Case must not throw away a
        # boundary the user just clicked out; they can pick a case and press
        # 완료 again without having to re-click every node.
        case_id = self.canvas.active_load_case_id
        if case_id is None:
            self.load3d_status_label.setText("⚠ 먼저 Load Case를 선택하거나 Definitions에서 만드세요.")
            return
        boundary = self.canvas.finish_floor_picking()
        if boundary is None:
            return  # fewer than 3 distinct nodes - the button should be disabled anyway
        self._reset_floor_boundary_picking_ui()
        payload = FloorLoadEntry(
            magnitude=self.load3d_floor_magnitude.value(),
            direction=self.load3d_floor_direction.currentData(),
            distribution=self.load3d_floor_distribution.currentData(),
            span_direction=self.load3d_floor_span_direction.currentData(),
            target_nodes=boundary,
        )
        self._commit_load3d_entry(case_id, "floor", boundary, payload)


    def _cancel_floor_boundary_picking(self) -> None:
        self.canvas.cancel_floor_picking()
        self._reset_floor_boundary_picking_ui()


    def _apply_load3d(self) -> None:
        case_id = self.canvas.active_load_case_id
        if case_id is None:
            self.load3d_status_label.setText("⚠ 먼저 Load Case를 선택하거나 Definitions에서 만드세요.")
            return
        kind = self._current_load3d_top_kind()
        if kind == "nodal":
            targets = tuple(self.canvas.selected_nodes)
            if not targets:
                self.load3d_status_label.setText("⚠ 절점을 선택하세요.")
                return
            fields = {key: spin.value() for key, spin in self.load3d_nodal_fields.items()}
            payload = NodalLoadEntry(coordinate_system=self.load3d_nodal_coord.currentData(), **fields)
            self._commit_load3d_entry(case_id, "nodal", targets, payload)
        elif kind == "member":
            targets = tuple(self.canvas.selected_elements)
            if not targets:
                self.load3d_status_label.setText("⚠ 부재를 선택하세요.")
                return
            subtype = self._current_load3d_member_subtype()
            coordinate_system = self.load3d_member_coord.currentData()
            direction = self.load3d_member_direction.currentText().lower()
            position_unit = self.load3d_member_position_unit.currentData()
            if subtype in ("member_point", "member_moment"):
                payload = MemberPointLoadEntry(
                    coordinate_system=coordinate_system,
                    direction=direction,
                    value=self.load3d_member_start_value.value(),
                    position=self.load3d_member_start_position.value(),
                    position_unit=position_unit,
                )
            else:
                start_value = self.load3d_member_start_value.value()
                end_value = start_value if subtype == "member_uniform" else self.load3d_member_end_value.value()
                if subtype == "member_partial":
                    start_position = self.load3d_member_start_position.value()
                    end_position = self.load3d_member_end_position.value()
                else:
                    start_position, end_position = 0.0, 1.0
                payload = MemberDistributedLoadEntry(
                    coordinate_system=coordinate_system,
                    direction=direction,
                    start_value=start_value,
                    end_value=end_value,
                    start_position=start_position,
                    end_position=end_position,
                    position_unit=position_unit,
                )
            self._commit_load3d_entry(case_id, subtype, targets, payload)
        elif kind == "floor":
            targets = tuple(sorted(self.canvas.selected_nodes))
            if len(targets) < 3:
                self.load3d_status_label.setText("⚠ 폐합영역을 이룰 절점을 3개 이상 선택하세요.")
                return
            payload = FloorLoadEntry(
                magnitude=self.load3d_floor_magnitude.value(),
                direction=self.load3d_floor_direction.currentData(),
                distribution=self.load3d_floor_distribution.currentData(),
                span_direction=self.load3d_floor_span_direction.currentData(),
                target_nodes=targets,
            )
            self._commit_load3d_entry(case_id, "floor", targets, payload)
        elif kind == "self_weight":
            apply_all = self.load3d_self_weight_apply_all.isChecked()
            targets = () if apply_all else tuple(self.canvas.selected_elements)
            if not apply_all and not targets:
                self.load3d_status_label.setText("⚠ 부재를 선택하거나 '전체 부재에 적용'을 체크하세요.")
                return
            payload = SelfWeightEntry(
                factor_x=self.load3d_self_weight_fx.value(),
                factor_y=self.load3d_self_weight_fy.value(),
                factor_z=self.load3d_self_weight_fz.value(),
                apply_to_all=apply_all,
                target_elements=targets,
            )
            self._commit_load3d_entry(case_id, "self_weight", targets, payload)


    def _commit_load3d_entry(self, case_id: str, kind: str, targets: tuple[int, ...], payload: object) -> None:
        if self._editing_load_entry_id is not None:
            self.canvas.update_load_entry(self._editing_load_entry_id, target=targets, payload=payload)
            self._editing_load_entry_id = None
            self.load3d_apply_button.setText("적용")
            self.load3d_status_label.setText("✓ 수정되었습니다.")
        elif self._current_load_apply_mode() == "delete":
            removed = self._remove_matching_load_entries(case_id, kind, targets)
            self.load3d_status_label.setText(
                f"✓ 일치하는 하중 {removed}개를 삭제했습니다."
                if removed
                else "⚠ 선택 대상에서 삭제할 일치 하중을 찾지 못했습니다."
            )
        else:
            if self._current_load_apply_mode() == "replace":
                self._remove_matching_load_entries(case_id, kind, targets)
            self.canvas.add_load_entry(case_id, kind, targets, payload)
            self.load3d_status_label.setText("✓ 적용되었습니다.")
        self._refresh_load3d_viewport()


    def _remove_matching_load_entries(
        self, case_id: str, kind: str, targets: tuple[int, ...]
    ) -> int:
        normalized_target = tuple(sorted(targets))
        matches = [
            entry_id
            for entry_id, entry in self.canvas.load_entries.items()
            if entry.case_id == case_id
            and entry.kind == kind
            and tuple(sorted(entry.target)) == normalized_target
        ]
        for entry_id in matches:
            self.canvas.delete_load_entry(entry_id)
        return len(matches)


    def _load_entry_display_id(self, entry) -> str:
        for kinds, _label, prefix in self._LOAD3D_KIND_GROUPS:
            if entry.kind not in kinds:
                continue
            siblings = sorted(
                (e for e in self.canvas.load_entries.values() if e.case_id == entry.case_id and e.kind in kinds),
                key=lambda e: e.id,
            )
            index = siblings.index(entry) + 1
            return f"{prefix}-{index:03d}"
        return f"#{entry.id}"


    def _show_selected_load(self, entry_id: int) -> None:
        entry = self.canvas.load_entries.get(entry_id)
        if entry is None:
            return
        self._selected_load_id = entry_id
        case = self.canvas.load_cases.get(entry.case_id)
        display_id = self._load_entry_display_id(entry)
        self.selection_status_panel.show_load_entry(entry, case, display_id, self._unit_system)
        if hasattr(self, "load_inspector_status_panel"):
            self.load_inspector_status_panel.show_load_entry(
                entry, case, display_id, self._unit_system
            )


    def _populate_load3d_form(self, entry) -> None:
        payload = entry.payload
        if entry.kind == "nodal":
            index = self.load3d_nodal_coord.findData(payload.coordinate_system)
            if index >= 0:
                self.load3d_nodal_coord.setCurrentIndex(index)
            for key, spin in self.load3d_nodal_fields.items():
                spin.setValue(getattr(payload, key))
        elif entry.kind in ("member_point", "member_moment", "member_uniform", "member_linear", "member_partial"):
            index = self.load3d_member_coord.findData(payload.coordinate_system)
            if index >= 0:
                self.load3d_member_coord.setCurrentIndex(index)
            self.load3d_member_direction.setCurrentText(payload.direction.upper())
            if hasattr(payload, "value"):
                self.load3d_member_start_value.setValue(payload.value)
                self.load3d_member_start_position.setValue(payload.position)
            else:
                self.load3d_member_start_value.setValue(payload.start_value)
                self.load3d_member_end_value.setValue(payload.end_value)
                self.load3d_member_start_position.setValue(payload.start_position)
                self.load3d_member_end_position.setValue(payload.end_position)
            unit_index = self.load3d_member_position_unit.findData(payload.position_unit)
            if unit_index >= 0:
                self.load3d_member_position_unit.setCurrentIndex(unit_index)
        elif entry.kind == "floor":
            self.load3d_floor_magnitude.setValue(payload.magnitude)
            direction_index = self.load3d_floor_direction.findData(payload.direction)
            if direction_index >= 0:
                self.load3d_floor_direction.setCurrentIndex(direction_index)
            distribution_index = self.load3d_floor_distribution.findData(payload.distribution)
            if distribution_index >= 0:
                self.load3d_floor_distribution.setCurrentIndex(distribution_index)
            span_index = self.load3d_floor_span_direction.findData(payload.span_direction)
            if span_index >= 0:
                self.load3d_floor_span_direction.setCurrentIndex(span_index)
        elif entry.kind == "self_weight":
            self.load3d_self_weight_fx.setValue(payload.factor_x)
            self.load3d_self_weight_fy.setValue(payload.factor_y)
            self.load3d_self_weight_fz.setValue(payload.factor_z)
            self.load3d_self_weight_apply_all.setChecked(payload.apply_to_all)


    def _edit_load_entry(self, entry_id: int) -> None:
        entry = self.canvas.load_entries.get(entry_id)
        if entry is None:
            return
        self._editing_load_entry_id = entry_id
        self.canvas.active_load_case_id = entry.case_id
        self._refresh_load_case_combo()
        command_index = self.load_command_combo.findData(entry.kind)
        if command_index >= 0:
            self.load_command_combo.setCurrentIndex(command_index)
        # Existing entries are edited through the case-based form even when
        # new nodal/uniform/linear loads use the solver-connected form. This
        # preserves the entry id and updates in place rather than creating a
        # second load when Apply is pressed.
        self.load_command_stack.setCurrentIndex(self.load_command_pages["entry"])
        top_kind = "member" if entry.kind.startswith("member_") else entry.kind
        type_index = self.load3d_type_combo.findData(top_kind)
        if type_index >= 0:
            self.load3d_type_combo.setCurrentIndex(type_index)
        subtype_index = self.load3d_member_subtype_combo.findData(entry.kind)
        if subtype_index >= 0:
            self.load3d_member_subtype_combo.setCurrentIndex(subtype_index)
        self._populate_load3d_form(entry)
        self.load3d_command_title.setText(
            f"{self._load_entry_display_id(entry)} 수정"
        )
        self.load_apply_mode_buttons["replace"].setChecked(True)
        self.load3d_apply_button.setText("수정 적용")
        self.load3d_status_label.setText(f"'{self._load_entry_display_id(entry)}' 수정 중 - 값을 바꾸고 적용을 누르세요.")
        self._show_category("load")
        if hasattr(self, "load_category_pages"):
            # Land on Direct Loads (where the quick/entry forms above live) -
            # otherwise editing an entry from a tree while Definitions/
            # Generators/Combinations was showing would update the form data
            # without the form itself ever becoming visible.
            self.load_category_stack.setCurrentIndex(self.load_category_pages["direct"])


    def _reselect_load_entry_target(self, entry_id: int) -> None:
        entry = self.canvas.load_entries.get(entry_id)
        if entry is None:
            return
        if entry.kind in ("nodal", "floor"):
            self.canvas.selected_nodes = set(entry.target)
            self.canvas.selected_elements.clear()
        else:
            self.canvas.selected_elements = set(entry.target)
            self.canvas.selected_nodes.clear()
        self.canvas.selection_changed.emit()
        self._edit_load_entry(entry_id)


    def _delete_load_entry_from_status(self, entry_id: int) -> None:
        self.canvas.delete_load_entry(entry_id)
        if getattr(self, "_selected_load_id", None) == entry_id:
            self._selected_load_id = None
            self._sync_selection_status()


    def _refresh_load_tree(self) -> None:
        if not hasattr(self, "_load_tree_bindings"):
            return
        for binding in self._load_tree_bindings:
            self._refresh_load_tree_binding(binding)


    def _refresh_load_tree_binding(self, binding: _LoadTreeBinding) -> None:
        tree, combinations_item, case_items = binding
        combinations_item.takeChildren()
        for combination in self.canvas.load_combinations.values():
            factor_text = ", ".join(
                f"{kind.value} {factor:g}" for kind, factor in combination.factors.items()
            )
            leaf = QTreeWidgetItem([combination.name, ""])
            leaf.setToolTip(0, factor_text or "계수 없음")
            combinations_item.addChild(leaf)
        combinations_item.setText(1, str(len(self.canvas.load_combinations)))
        combinations_item.setExpanded(True)

        for case_id in list(case_items.keys()):
            if case_id not in self.canvas.load_cases:
                item = case_items.pop(case_id)
                index = tree.indexOfTopLevelItem(item)
                if index >= 0:
                    tree.takeTopLevelItem(index)

        for case in self.canvas.load_cases.values():
            item = case_items.get(case.id)
            if item is None:
                item = QTreeWidgetItem(["", ""])
                case_items[case.id] = item
                tree.addTopLevelItem(item)
            item.setText(0, case.name)
            item.setForeground(0, QBrush(QColor(LOAD_CASE_PRESENTATION[case.kind][1])))
            item.takeChildren()
            case_entries = [entry for entry in self.canvas.load_entries.values() if entry.case_id == case.id]
            item.setText(1, str(len(case_entries)))
            for kinds, label, prefix in self._LOAD3D_KIND_GROUPS:
                group_entries = sorted(
                    (entry for entry in case_entries if entry.kind in kinds), key=lambda e: e.id
                )
                if not group_entries:
                    continue
                group_item = QTreeWidgetItem([f"{label} ({len(group_entries)})", ""])
                item.addChild(group_item)
                for index, entry in enumerate(group_entries, start=1):
                    leaf = QTreeWidgetItem([f"{prefix}-{index:03d}", ""])
                    leaf.setData(0, Qt.ItemDataRole.UserRole, entry.id)
                    if entry.hidden:
                        leaf.setForeground(0, QBrush(QColor("#9ca3af")))
                    group_item.addChild(leaf)
            item.setExpanded(True)


    def _on_work_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        entry_id = item.data(0, Qt.ItemDataRole.UserRole)
        if entry_id is not None:
            self._show_selected_load(int(entry_id))
            return
        entity = item.data(0, _TREE_ENTITY_ROLE)
        if entity is not None:
            self._select_entity_from_tree(*entity)


    def _show_load_tree_context_menu(self, tree: QTreeWidget, position) -> None:
        item = tree.itemAt(position)
        if item is None:
            return
        entry_id = item.data(0, Qt.ItemDataRole.UserRole)
        if entry_id is None:
            entity = item.data(0, _TREE_ENTITY_ROLE)
            if entity is not None:
                self._show_geometry_tree_context_menu(tree, position, entity)
                return
            definition = item.data(0, _TREE_DEFINITION_ROLE)
            if definition is not None:
                self._show_definition_tree_context_menu(tree, position, definition)
            return
        entry_id = int(entry_id)
        entry = self.canvas.load_entries.get(entry_id)
        if entry is None:
            return
        menu = QMenu(tree)
        edit_action = menu.addAction("Edit")
        duplicate_action = menu.addAction("Duplicate")
        hide_action = menu.addAction("Show" if entry.hidden else "Hide")
        delete_action = menu.addAction("Delete")
        move_menu = menu.addMenu("Move to Load Case")
        move_actions = {}
        for case in self.canvas.load_cases.values():
            if case.id == entry.case_id:
                continue
            move_actions[move_menu.addAction(case.name)] = case.id
        chosen = menu.exec(tree.viewport().mapToGlobal(position))
        if chosen is None:
            return
        if chosen is edit_action:
            self._edit_load_entry(entry_id)
        elif chosen is duplicate_action:
            self.canvas.duplicate_load_entry(entry_id)
        elif chosen is hide_action:
            self.canvas.set_load_entry_hidden(entry_id, not entry.hidden)
        elif chosen is delete_action:
            self.canvas.delete_load_entry(entry_id)
            if getattr(self, "_selected_load_id", None) == entry_id:
                self._selected_load_id = None
                self._sync_selection_status()
        elif chosen in move_actions:
            self.canvas.move_load_entry_to_case(entry_id, move_actions[chosen])


    def _show_geometry_tree_context_menu(
        self, tree: QTreeWidget, position, entity: tuple[str, int]
    ) -> None:
        """Right-click menu for a Work Tree 절점/부재/지점 row - jumps to the
        existing 부재/지점 category editor (so editing reuses the exact same
        form ``_apply_member_section``/``_apply_support`` already write
        through) or deletes the entity outright. No confirmation prompt:
        the DELETE toolbar button already removes a selection with none,
        Ctrl+Z is the same safety net either way.
        """
        kind, tag = entity
        item = tree.itemAt(position)
        is_support_row = kind == "node" and item is not None and item.parent() is self.work_tree_supports
        menu = QMenu(tree)
        edit_action = None
        release_action = None
        if kind == "element":
            edit_action = menu.addAction("단면·재료 편집")
            delete_action = menu.addAction("부재 삭제")
        elif is_support_row:
            edit_action = menu.addAction("구속조건 편집")
            release_action = menu.addAction("지점 해제")
            delete_action = menu.addAction("절점 삭제")
        else:
            delete_action = menu.addAction("절점 삭제")
        chosen = menu.exec(tree.viewport().mapToGlobal(position))
        if chosen is None:
            return
        self._select_entity_from_tree(kind, tag)
        if edit_action is not None and chosen is edit_action:
            self._show_category("member" if kind == "element" else "support")
        elif release_action is not None and chosen is release_action:
            self.canvas.remove_support(tag)
        elif chosen is delete_action:
            self.canvas.delete_selected()


    def _show_definition_tree_context_menu(
        self, tree: QTreeWidget, position, definition: tuple[str, str]
    ) -> None:
        """Right-click menu for a Work Tree 물성/섹션 row. Deleting a
        definition only removes it from this picker list - members that
        already had it applied keep their own copied E/A/I/... values (see
        ``apply_full_section_to_selection``), so nothing already built breaks.
        """
        kind, definition_id = definition
        menu = QMenu(tree)
        delete_action = menu.addAction("삭제")
        chosen = menu.exec(tree.viewport().mapToGlobal(position))
        if chosen is not delete_action:
            return
        if kind == "material":
            self._user_materials[:] = [
                entry for entry in self._user_materials if entry.get("id") != definition_id
            ]
        else:
            self._user_sections[:] = [
                entry for entry in self._user_sections if entry.get("id") != definition_id
            ]
        self._refresh_work_tree()

