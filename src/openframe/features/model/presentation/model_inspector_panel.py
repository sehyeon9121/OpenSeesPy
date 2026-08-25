"""Contextual model properties and analysis-readiness guidance."""

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    StructuralModel,
    SupportKind,
    UnitSystem,
)

SUPPORT_LABELS = {
    SupportKind.FIXED: "Fixed",
    SupportKind.PINNED: "Pinned",
    SupportKind.ROLLER_VERTICAL: "Vertical Roller",
    SupportKind.ROLLER_HORIZONTAL: "Horizontal Roller",
    SupportKind.ROLLER_X: "X Roller",
    SupportKind.ROLLER_Y: "Y Roller",
    SupportKind.ROLLER_Z: "Z Roller",
    SupportKind.CUSTOM: "Custom Restraint",
}


class ModelInspectorPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelInspectorPanel")
        self._model: StructuralModel | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self.selection_identity: tuple[str, int] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("panelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 9, 14, 9)
        header_layout.addWidget(QLabel("MODEL INSPECTOR"))
        header_layout.addStretch(1)
        self.model_badge = QLabel("NO MODEL")
        self.model_badge.setObjectName("waitingBadge")
        header_layout.addWidget(self.model_badge)
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("inspectorTabs")
        self.tabs.addTab(self._build_selection_page(), "SELECTION")
        self.tabs.addTab(self._build_readiness_page(), "READINESS")
        layout.addWidget(self.tabs, 1)
        self._show_empty_selection()
        self._refresh_readiness()

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self.selection_identity = None
        self.model_badge.setText("MODEL READY")
        self.model_badge.setObjectName("smallBadge")
        self.model_badge.style().unpolish(self.model_badge)
        self.model_badge.style().polish(self.model_badge)
        self._show_empty_selection()
        self._refresh_readiness()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        if self.selection_identity is not None:
            self.select_entity(*self.selection_identity)

    def select_entity(self, kind: str, tag: int) -> None:
        if self._model is None:
            return
        self.selection_identity = (kind, tag)
        handlers = {
            "node": self._show_node,
            "element": self._show_element,
            "support": self._show_support,
            "load": self._show_load,
            "element_load": self._show_element_load,
        }
        handler = handlers.get(kind)
        if handler is None:
            self._show_empty_selection()
            return
        handler(tag)
        self.tabs.setCurrentIndex(0)

    def _build_selection_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("inspectorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        self.entity_badge = QLabel("SELECT")
        self.entity_badge.setObjectName("inspectorEntityBadge")
        self.entity_title = QLabel("No selection")
        self.entity_title.setObjectName("inspectorEntityTitle")
        heading.addWidget(self.entity_badge)
        heading.addWidget(self.entity_title, 1)
        layout.addLayout(heading)

        self.entity_visual = QLabel()
        self.entity_visual.setObjectName("inspectorEntityVisual")
        self.entity_visual.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.entity_visual.setMinimumHeight(46)
        layout.addWidget(self.entity_visual)

        self.entity_description = QLabel()
        self.entity_description.setObjectName("secondaryText")
        self.entity_description.setWordWrap(True)
        layout.addWidget(self.entity_description)

        essential = QLabel("ESSENTIAL PROPERTIES")
        essential.setObjectName("resultGroupLabel")
        layout.addWidget(essential)
        self.property_grid = QGridLayout()
        self.property_grid.setHorizontalSpacing(7)
        self.property_grid.setVerticalSpacing(7)
        self.property_cards: list[tuple[QFrame, QLabel, QLabel]] = []
        for index in range(6):
            card = QFrame()
            card.setObjectName("inspectorPropertyCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(1)
            name = QLabel()
            name.setObjectName("inspectorPropertyName")
            value = QLabel()
            value.setObjectName("inspectorPropertyValue")
            value.setWordWrap(True)
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            self.property_grid.addWidget(card, index // 2, index % 2)
            self.property_cards.append((card, name, value))
        layout.addLayout(self.property_grid)

        advanced = QLabel("DERIVED / ADVANCED")
        advanced.setObjectName("resultGroupLabel")
        layout.addWidget(advanced)
        self.advanced_text = QLabel()
        self.advanced_text.setObjectName("inspectorAdvancedText")
        self.advanced_text.setWordWrap(True)
        layout.addWidget(self.advanced_text)
        layout.addStretch(1)
        return page

    def _build_readiness_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("inspectorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(7)

        intro = QLabel(
            "Checks which analyses can be performed with the information detected "
            "in the imported OpenSeesPy model."
        )
        intro.setObjectName("secondaryText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.readiness_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title in (
            ("geometry", "Geometry"),
            ("connectivity", "Connectivity"),
            ("boundary", "Boundary Conditions"),
            ("static", "Static Force Analysis"),
            ("displacement", "Displacement Analysis"),
            ("nonlinear", "Nonlinear Analysis"),
            ("history", "Time History Analysis"),
        ):
            row = QFrame()
            row.setObjectName("readinessRow")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(9, 6, 9, 6)
            row_layout.setSpacing(1)
            top = QHBoxLayout()
            name = QLabel(title)
            name.setObjectName("readinessName")
            status = QLabel("WAITING")
            status.setObjectName("readinessWaiting")
            top.addWidget(name)
            top.addStretch(1)
            top.addWidget(status)
            detail = QLabel("Load a model to run this check.")
            detail.setObjectName("readinessDetail")
            detail.setWordWrap(True)
            row_layout.addLayout(top)
            row_layout.addWidget(detail)
            layout.addWidget(row)
            self.readiness_rows[key] = (status, detail)
        layout.addStretch(1)
        return page

    def _show_empty_selection(self) -> None:
        self.entity_badge.setText("GUIDE")
        self.entity_title.setText("Select a model entity")
        self.entity_visual.setText("●  NODE     ━━━     ELEMENT     ●")
        if self._model is None:
            self.entity_description.setText(
                "Upload an OpenSeesPy file, then select a node, element, support or load."
            )
        else:
            self.entity_description.setText(
                "Click an item in the model tree or structural viewport to inspect it."
            )
        self._set_properties([])
        self.advanced_text.setText("No entity selected.")

    def _show_node(self, tag: int) -> None:
        assert self._model is not None
        node = self._model.nodes.get(tag)
        if node is None:
            return
        unit = self._unit_system
        boundary = next((item for item in self._model.boundaries if item.node_tag == tag), None)
        loads = [item for item in self._model.nodal_loads if item.node_tag == tag]
        support = SUPPORT_LABELS[boundary.support_kind] if boundary else "Free"
        values = [0.0] * max(self._model.ndf, 3)
        for load in loads:
            for index, value in enumerate(load.values[: len(values)]):
                values[index] += value
        self.entity_badge.setText("NODE")
        self.entity_title.setText(f"Node {tag}")
        dof_text = "UX  UY  UZ  RX  RY  RZ" if self._model.ndm == 3 else "UX  UY  RZ"
        self.entity_visual.setText(f"● {tag}   {dof_text}")
        self.entity_description.setText(
            "Coordinate, degrees of freedom, support and resultant nodal load."
        )
        properties = [
            ("X", f"{node.x:g} {unit.length}"),
            ("Y", f"{node.y:g} {unit.length}"),
        ]
        if self._model.ndm == 3:
            properties.extend(
                [
                    ("Z", f"{node.z:g} {unit.length}"),
                    ("DOF", f"{node.ndf} (3 translations + 3 rotations)"),
                    ("SUPPORT", support),
                    (
                        "Fx / Fy / Fz",
                        " / ".join(f"{value:g}" for value in values[:3]) + f" {unit.force}",
                    ),
                ]
            )
        else:
            properties.extend(
                [
                    ("DOF", f"{node.ndf} (UX, UY, RZ)"),
                    ("SUPPORT", support),
                    ("Fx / Fy", f"{values[0]:g} / {values[1]:g} {unit.force}"),
                    ("Mz", f"{values[2]:g} {unit.moment}"),
                ]
            )
        self._set_properties(properties)
        self.advanced_text.setText(
            "Restraints: "
            + (
                " ".join("LOCKED" if value else "FREE" for value in boundary.restraints)
                if boundary
                else "All active DOFs are free."
            )
        )

    def _show_element(self, tag: int) -> None:
        assert self._model is not None
        element = self._model.elements.get(tag)
        if element is None:
            return
        node_i = self._model.nodes[element.node_i]
        node_j = self._model.nodes[element.node_j]
        length = math.sqrt(
            (node_j.x - node_i.x) ** 2 + (node_j.y - node_i.y) ** 2 + (node_j.z - node_i.z) ** 2
        )
        unit = self._unit_system
        area = self._number_property(element.properties, "A")
        elastic_modulus = self._number_property(element.properties, "E")
        inertia = self._number_property(element.properties, "I")
        inertia_y = self._number_property(element.properties, "Iy")
        inertia_z = self._number_property(element.properties, "Iz")
        self.entity_badge.setText("ELEMENT")
        self.entity_title.setText(f"Element {tag}")
        self.entity_visual.setText(f"● Node {element.node_i}   ━━━━━   Node {element.node_j} ●")
        self.entity_description.setText(element.element_type)
        properties = [
            ("LENGTH", f"{length:.5g} {unit.length}"),
            ("NODES", f"{element.node_i}  →  {element.node_j}"),
            ("E", self._property_text(elastic_modulus, f"{unit.force}/{unit.length}²")),
            ("A", self._property_text(area, f"{unit.length}²")),
        ]
        if self._model.ndm == 3:
            properties.extend(
                [
                    ("Iy", self._property_text(inertia_y, f"{unit.length}⁴")),
                    ("Iz", self._property_text(inertia_z, f"{unit.length}⁴")),
                ]
            )
        else:
            properties.extend(
                [
                    ("I", self._property_text(inertia, f"{unit.length}⁴")),
                    ("TRANSFORM", str(element.properties.get("transf_tag", "Not detected"))),
                ]
            )
        self._set_properties(properties)
        derived = []
        if elastic_modulus is not None and area is not None:
            derived.append(f"EA = {elastic_modulus * area:.6g} {unit.force}")
        if elastic_modulus is not None and inertia is not None:
            derived.append(f"EI = {elastic_modulus * inertia:.6g} {unit.force}·{unit.length}²")
        for axis, axis_inertia in (("y", inertia_y), ("z", inertia_z)):
            if elastic_modulus is not None and axis_inertia is not None:
                derived.append(
                    f"EI{axis} = {elastic_modulus * axis_inertia:.6g} {unit.force}·{unit.length}²"
                )
        if self._model.ndm == 3:
            shear_modulus = self._number_property(element.properties, "G")
            torsion = self._number_property(element.properties, "J")
            if shear_modulus is not None and torsion is not None:
                derived.append(f"GJ = {shear_modulus * torsion:.6g} {unit.force}·{unit.length}²")
        self.advanced_text.setText(
            "   |   ".join(derived) if derived else "No derived stiffness is available."
        )

    def _show_support(self, tag: int) -> None:
        assert self._model is not None
        boundary = next((item for item in self._model.boundaries if item.node_tag == tag), None)
        if boundary is None:
            return
        restraint_names = (
            ("UX", "UY", "UZ", "RX", "RY", "RZ") if self._model.ndm == 3 else ("UX", "UY", "RZ")
        )
        self.entity_badge.setText("SUPPORT")
        self.entity_title.setText(f"Node {tag} · {SUPPORT_LABELS[boundary.support_kind]}")
        self.entity_visual.setText("━━━  ●  ┻┻┻")
        self.entity_description.setText("Boundary-condition restraints by degree of freedom.")
        self._set_properties(
            [
                (
                    name,
                    "LOCKED"
                    if index < len(boundary.restraints) and boundary.restraints[index]
                    else "FREE",
                )
                for index, name in enumerate(restraint_names)
            ]
        )
        restraint_code = "".join("1" if value else "0" for value in boundary.restraints)
        self.advanced_text.setText(f"OpenSees restraint code: [{restraint_code}]")

    def _show_load(self, tag: int) -> None:
        assert self._model is not None
        unit = self._unit_system
        loads = [item for item in self._model.nodal_loads if item.node_tag == tag]
        values = [0.0] * max(self._model.ndf, 3)
        for load in loads:
            for index, value in enumerate(load.values[: len(values)]):
                values[index] += value
        self.entity_badge.setText("LOAD")
        self.entity_title.setText(f"Nodal Load · Node {tag}")
        self.entity_visual.setText(
            "Fx  Fy  Fz  Mx  My  Mz" if self._model.ndm == 3 else "→  Fx      ↓  Fy      ↻  Mz"
        )
        self.entity_description.setText("하중 케이스 색상으로 구분되어 구조 뷰포트에 표시됩니다.")
        if self._model.ndm == 3:
            names = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")
            properties = [
                (
                    name,
                    f"{values[index]:g} {unit.force if index < 3 else unit.moment}",
                )
                for index, name in enumerate(names)
            ]
        else:
            properties = [
                ("Fx", f"{values[0]:g} {unit.force}"),
                ("Fy", f"{values[1]:g} {unit.force}"),
                ("Mz", f"{values[2]:g} {unit.moment}"),
                ("PATTERN", str(loads[0].pattern_tag or "Imported") if loads else "None"),
            ]
        self._set_properties(properties)
        case_summary = ", ".join(
            sorted({f"{load.case_type.value} (Pattern {load.pattern_tag})" for load in loads})
        )
        self.advanced_text.setText(
            f"{len(loads)}개 load 명령 집계 | {case_summary or 'UNCLASSIFIED'}"
        )

    def _show_element_load(self, tag: int) -> None:
        assert self._model is not None
        unit = self._unit_system
        loads = [item for item in self._model.element_loads if item.element_tag == tag]
        wx = sum(load.wx for load in loads)
        wy = sum(load.wy for load in loads)
        wz = sum(load.wz for load in loads)
        load_unit = f"{unit.force}/{unit.length}"
        self.entity_badge.setText("ELEMENT LOAD")
        self.entity_title.setText(f"Uniform Load · Element {tag}")
        self.entity_visual.setText("↓↓↓↓↓  beamUniform  ↓↓↓↓↓")
        self.entity_description.setText(
            "Uniformly distributed load components in the member local axes."
        )
        self._set_properties(
            [
                ("Wx (LOCAL)", f"{wx:g} {load_unit}"),
                ("Wy (LOCAL)", f"{wy:g} {load_unit}"),
                ("Wz (LOCAL)", f"{wz:g} {load_unit}"),
                ("PATTERN", str(loads[0].pattern_tag or "Imported") if loads else "None"),
            ]
        )
        self.advanced_text.setText(
            f"{len(loads)}개 beamUniform 명령 집계 | "
            + ", ".join(
                sorted({f"{load.case_type.value} (Pattern {load.pattern_tag})" for load in loads})
            )
        )

    def _set_properties(self, properties: list[tuple[str, str]]) -> None:
        for index, (card, name, value) in enumerate(self.property_cards):
            if index < len(properties):
                property_name, property_value = properties[index]
                name.setText(property_name)
                value.setText(property_value)
                card.show()
            else:
                card.hide()

    def _refresh_readiness(self) -> None:
        model = self._model
        if model is None:
            for status, detail in self.readiness_rows.values():
                self._set_readiness(status, detail, "WAITING", "Load a model to run this check.")
            return

        validation_errors = model.validate()
        geometry_ready = bool(model.nodes and model.elements)
        connectivity_ready = not validation_errors
        boundary_ready = bool(model.boundaries)
        missing_stiffness = self._missing_stiffness_properties(model)

        self._set_readiness(
            *self.readiness_rows["geometry"],
            "READY" if geometry_ready else "MISSING",
            "Nodes and elements were detected."
            if geometry_ready
            else "No structural geometry detected.",
        )
        self._set_readiness(
            *self.readiness_rows["connectivity"],
            "READY" if connectivity_ready else "ERROR",
            "All element nodes exist." if connectivity_ready else validation_errors[0],
        )
        self._set_readiness(
            *self.readiness_rows["boundary"],
            "READY" if boundary_ready else "MISSING",
            "Supports were detected."
            if boundary_ready
            else "No restrained degrees of freedom detected.",
        )
        static_ready = geometry_ready and connectivity_ready and boundary_ready
        self._set_readiness(
            *self.readiness_rows["static"],
            "READY" if static_ready else "MISSING",
            "Static equilibrium can be evaluated."
            if static_ready
            else "Complete geometry and supports first.",
        )
        displacement_ready = static_ready and not missing_stiffness
        self._set_readiness(
            *self.readiness_rows["displacement"],
            "READY" if displacement_ready else "MISSING",
            "Required stiffness properties were detected."
            if displacement_ready
            else f"Missing stiffness: {', '.join(missing_stiffness) or 'model stability'}.",
        )
        self._set_readiness(
            *self.readiness_rows["nonlinear"],
            "MISSING",
            "Nonlinear material or section behavior is not yet detected.",
        )
        self._set_readiness(
            *self.readiness_rows["history"],
            "MISSING",
            "Mass, damping and ground-motion data are required.",
        )

    @staticmethod
    def _set_readiness(status: QLabel, detail: QLabel, state: str, message: str) -> None:
        status.setText(state)
        object_names = {
            "READY": "readinessReady",
            "MISSING": "readinessMissing",
            "ERROR": "readinessError",
            "WAITING": "readinessWaiting",
        }
        status.setObjectName(object_names[state])
        status.style().unpolish(status)
        status.style().polish(status)
        detail.setText(message)

    @classmethod
    def _missing_stiffness_properties(cls, model: StructuralModel) -> list[str]:
        missing: list[str] = []
        for element in model.elements.values():
            if element.element_type.lower() == "elasticbeamcolumn":
                required = ("E", "A", "G", "J", "Iy", "Iz") if model.ndm == 3 else ("E", "A", "I")
                absent = [key for key in required if key not in element.properties]
                if absent:
                    missing.append(f"Element {element.tag} ({'/'.join(absent)})")
            elif element.element_type.lower() in {"truss", "corottruss"}:
                absent = [key for key in ("A", "material_tag") if key not in element.properties]
                if absent:
                    missing.append(f"Element {element.tag} ({'/'.join(absent)})")
        return missing

    @staticmethod
    def _number_property(properties: dict[str, float | str], key: str) -> float | None:
        value = properties.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _property_text(value: float | None, unit: str) -> str:
        return "NOT DETECTED" if value is None else f"{value:.6g} {unit}"
