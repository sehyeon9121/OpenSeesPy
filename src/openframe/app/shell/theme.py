"""Application shell theme shared by all feature presentation components."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

APPLICATION_STYLE = """
QMainWindow {
    background: #f5f7fa;
}
QWidget {
    font-size: 9pt;
    color: #243244;
}
QFrame#appHeader {
    background: #ffffff;
    border-bottom: 1px solid #d8dde4;
}
QLabel#brandMark {
    min-width: 30px;
    min-height: 30px;
    max-width: 30px;
    max-height: 30px;
    border-radius: 6px;
    background: #174ea6;
    color: #ffffff;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QLabel#brandName {
    font-size: 12pt;
    font-weight: 700;
    color: #14213d;
}
QLabel#readyBadge {
    color: #54705f;
    font-size: 8pt;
    padding-left: 8px;
}
QPushButton#uploadButton, QPushButton#runButton {
    min-height: 30px;
    border-radius: 4px;
    padding: 0 12px;
    font-weight: 600;
}
QPushButton#uploadButton {
    background: #ffffff;
    border: 1px solid #bdc8d5;
    color: #2d4059;
}
QPushButton#runButton {
    background: #174ea6;
    border: 1px solid #174ea6;
    color: #ffffff;
}
QPushButton#uploadButton:hover { background: #f3f6fa; }
QPushButton#runButton:hover { background: #123f89; }
QFrame#workspaceNavigation {
    background: #ffffff;
    border-bottom: 1px solid #d8dde4;
    min-height: 38px;
}
QFrame#workspaceNavigation QToolButton {
    min-width: 82px;
    min-height: 36px;
    background: transparent;
    border: 0;
    border-bottom: 3px solid transparent;
    color: #718096;
    font-size: 8pt;
    font-weight: 600;
}
QFrame#workspaceNavigation QToolButton:hover {
    color: #174ea6;
    background: #f7f9fc;
}
QFrame#workspaceNavigation QToolButton:checked {
    color: #174ea6;
    border-bottom-color: #174ea6;
}
QFrame#modelSidebar, QFrame#analysisSidebar {
    background: #f8fafc;
}
QFrame#modelSidebar { border-right: 1px solid #dce3eb; }
QFrame#analysisSidebar { border-left: 1px solid #dce3eb; }
QLabel#sectionLabel, QLabel#fieldLabel {
    color: #68778a;
    font-size: 8pt;
    font-weight: 600;
}
QFrame#panelCard {
    background: #ffffff;
    border: 1px solid #dce3eb;
    border-radius: 4px;
}
QLabel#fileName { font-weight: 600; color: #1e3555; }
QLabel#secondaryText { color: #8290a0; font-size: 8pt; }
QLabel#summaryLabel { color: #8a97a6; font-size: 8pt; }
QLabel#summaryValue { color: #25364d; font-weight: 600; }
QLabel#smallBadge, QLabel#waitingBadge {
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 7pt;
    font-weight: 600;
}
QLabel#supportLegend {
    color: #63748a;
    font-size: 8pt;
    padding-left: 10px;
}
QLabel#smallBadge { background: #e9f0fb; color: #174ea6; }
QLabel#waitingBadge { background: #f0f2f5; color: #778493; }
QTreeWidget#modelTree {
    background: #ffffff;
    border: 1px solid #dce3eb;
    border-radius: 4px;
    padding: 4px;
}
QTreeWidget#modelTree::item { min-height: 26px; }
QTreeWidget#modelTree::item:selected {
    background: #e9f0fb;
    color: #174ea6;
}
QFrame#panelHeader, QFrame#canvasHeader {
    background: #f2f5f8;
    border-bottom: 1px solid #dce3eb;
    min-height: 34px;
}
QFrame#panelHeader QLabel { font-size: 8pt; font-weight: 600; color: #415269; }
QFrame#rightSection { background: #ffffff; border-bottom: 1px solid #dce3eb; }
QComboBox {
    min-height: 29px;
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 3px;
    padding: 0 8px;
}
QTabWidget#resultTabs::pane { border: 0; border-top: 1px solid #e2e7ed; }
QTabWidget#resultTabs QTabBar::tab {
    background: transparent;
    color: #7c8998;
    min-width: 66px;
    padding: 7px 5px;
    border-bottom: 2px solid transparent;
}
QTabWidget#resultTabs QTabBar::tab:selected {
    color: #174ea6;
    border-bottom-color: #e5484d;
}
QLabel#resultLabel { color: #7a8796; font-size: 8pt; }
QLabel#resultValue { color: #d43e44; font-size: 16pt; font-weight: 600; }
QTableWidget {
    background: #ffffff;
    border: 1px solid #e1e7ee;
    gridline-color: #edf1f5;
}
QHeaderView::section {
    background: #f4f6f9;
    border: 0;
    border-bottom: 1px solid #dce3eb;
    padding: 5px;
    color: #6b7989;
    font-size: 8pt;
}
QFrame#modelViewport { background: #ffffff; }
QGraphicsView#structuralView { background: #fbfcfe; border: 0; }
QPushButton#canvasToolButton {
    min-width: 28px;
    min-height: 24px;
    background: #ffffff;
    border: 1px solid #ccd6e2;
    border-radius: 3px;
    padding: 0 6px;
    color: #415269;
}
QFrame#displayControls {
    background: #ffffff;
    border-top: 1px solid #dce3eb;
}
QFrame#displayControls QLabel { color: #748295; font-size: 8pt; }
QComboBox#forceUnitSelector, QComboBox#lengthUnitSelector {
    min-height: 24px;
    max-height: 24px;
    padding: 0 6px;
    color: #415269;
    font-size: 8pt;
}
QCheckBox { color: #57677a; font-size: 8pt; spacing: 4px; }
QSlider::groove:horizontal { height: 3px; background: #dce3eb; }
QSlider::handle:horizontal {
    width: 11px;
    margin: -4px 0;
    border-radius: 5px;
    background: #174ea6;
}
QFrame#resultsWorkspace { background: #eef2f6; }
QFrame#resultToolbar {
    background: #ffffff;
    border-bottom: 1px solid #cfd8e3;
}
QLabel#resultToolbarLabel, QLabel#resultGroupLabel {
    color: #718096;
    font-size: 7pt;
    font-weight: 700;
}
QComboBox#resultToolbarSelector {
    min-height: 25px;
    max-height: 25px;
    min-width: 125px;
    padding: 0 7px;
    font-size: 8pt;
}
QPushButton#resultPrimaryButton, QPushButton#resultSecondaryButton {
    min-height: 29px;
    padding: 0 11px;
    border-radius: 3px;
    font-size: 8pt;
    font-weight: 600;
}
QPushButton#resultPrimaryButton {
    color: #ffffff;
    background: #174ea6;
    border: 1px solid #174ea6;
}
QPushButton#resultSecondaryButton {
    color: #29405f;
    background: #ffffff;
    border: 1px solid #bdc9d8;
}
QFrame#resultTypeSidebar {
    background: #f3f6fa;
    border-right: 1px solid #d7e0ea;
}
QLabel#resultSectionTitle {
    color: #1f3452;
    font-size: 9pt;
    font-weight: 700;
    padding: 2px 0 0 0;
}
QLabel#resultTypeDescription {
    color: #77869a;
    font-size: 7pt;
    padding-bottom: 2px;
}
QFrame#resultTypeGroup {
    background: #ffffff;
    border: 1px solid #dce4ed;
    border-radius: 4px;
}
QLabel#resultTypeGroupTitle {
    color: #40546d;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#resultTypeGroupHint {
    color: #8996a6;
    font-size: 7pt;
    padding: 0 2px 3px 2px;
}
QLabel#resultTypeGroupCount {
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    border-radius: 8px;
    background: #e9eff7;
    color: #5f7188;
    font-size: 7pt;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QToolButton#resultTypeButton {
    min-height: 28px;
    padding: 0 8px;
    border: 0;
    border-left: 3px solid transparent;
    border-radius: 2px;
    background: #ffffff;
    color: #53657a;
    text-align: left;
    font-size: 8pt;
}
QToolButton#resultTypeButton:hover { background: #f0f5fb; color: #174ea6; }
QToolButton#resultTypeButton:checked {
    background: #e7effb;
    border-left-color: #174ea6;
    color: #174ea6;
    font-weight: 700;
}
QFrame#resultViewport { background: #ffffff; }
QFrame#resultCanvasHeader, QFrame#resultViewportControls,
QFrame#resultDataHeader {
    background: #f6f8fb;
    border-bottom: 1px solid #dbe3ec;
}
QLabel#resultModeBadge {
    color: #174ea6;
    background: #e7effb;
    border: 1px solid #cad9ef;
    border-radius: 3px;
    padding: 3px 7px;
    font-size: 7pt;
    font-weight: 700;
}
QPushButton#resultCanvasButton {
    min-width: 28px;
    min-height: 23px;
    padding: 0 5px;
    color: #40536b;
    background: #ffffff;
    border: 1px solid #c7d2df;
    border-radius: 2px;
}
QToolButton#resultGraphToolButton {
    min-width: 25px;
    min-height: 22px;
    padding: 0 4px;
    color: #40536b;
    background: #ffffff;
    border: 1px solid #c7d2df;
    border-radius: 2px;
    font-weight: 700;
}
QToolButton#resultGraphToolButton:hover {
    color: #174ea6;
    border-color: #8faed8;
    background: #edf3fa;
}
QGraphicsView#resultGraphicsView { background: #fbfcfe; border: 0; }
QLabel#resultScaleValue { color: #174ea6; font-weight: 700; min-width: 30px; }
QFrame#resultDataPanel {
    background: #ffffff;
    border-top: 1px solid #cfd8e3;
}
QLabel#resultDataTitle { color: #314863; font-size: 8pt; font-weight: 700; }
QComboBox#resultDataMemberSelector, QComboBox#resultMemberSelector {
    min-height: 24px;
    max-height: 24px;
    padding: 0 6px;
    font-size: 8pt;
}
QTabWidget#workspaceResultTabs::pane { border: 0; border-top: 1px solid #dbe3ec; }
QTabWidget#workspaceResultTabs QTabBar::tab {
    min-width: 74px;
    padding: 6px 8px;
    color: #738195;
    background: #f6f8fb;
    border-bottom: 2px solid transparent;
}
QTabWidget#workspaceResultTabs QTabBar::tab:selected {
    color: #174ea6;
    background: #ffffff;
    border-bottom-color: #174ea6;
    font-weight: 700;
}
QFrame#resultSummaryPanel {
    background: #ffffff;
    border-left: 1px solid #d7e0ea;
}
QFrame#resultMetricRow {
    background: #f8fafc;
    border: 1px solid #e0e7ef;
    border-radius: 2px;
}
QLabel#resultMetricLabel { color: #718096; font-size: 7pt; font-weight: 700; }
QLabel#resultMetricValue { color: #d43e44; font-size: 12pt; font-weight: 700; }
QProgressBar#resultLegend {
    min-height: 10px;
    max-height: 10px;
    border: 1px solid #d1dae5;
    background: #edf2f7;
}
QProgressBar#resultLegend::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2563eb, stop:0.5 #f7d154, stop:1 #e5484d);
}
QTableWidget#resultEndForceTable, QTableWidget#workspaceResultTable {
    font-family: "Consolas";
    font-size: 8pt;
}
QLabel#resultDetailsText { color: #596a7f; font-family: "Consolas"; font-size: 8pt; }
QFrame#modelInspectorPanel { background: #ffffff; }
QTabWidget#inspectorTabs::pane { border: 0; border-top: 1px solid #dce3eb; }
QTabWidget#inspectorTabs QTabBar::tab {
    min-width: 100px;
    padding: 7px 5px;
    color: #7c8998;
    background: #f7f9fc;
    border-bottom: 2px solid transparent;
}
QTabWidget#inspectorTabs QTabBar::tab:selected {
    color: #174ea6;
    background: #ffffff;
    border-bottom-color: #174ea6;
    font-weight: 700;
}
QWidget#inspectorPage { background: #ffffff; }
QLabel#inspectorEntityBadge {
    color: #ffffff;
    background: #174ea6;
    border-radius: 3px;
    padding: 3px 7px;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#inspectorEntityTitle { color: #223a59; font-size: 10pt; font-weight: 700; }
QLabel#inspectorEntityVisual {
    color: #174ea6;
    background: #f2f6fc;
    border: 1px solid #d6e1ef;
    border-radius: 3px;
    font-family: "Consolas";
    font-size: 9pt;
    font-weight: 600;
}
QFrame#inspectorPropertyCard {
    background: #f8fafc;
    border: 1px solid #dee6ef;
    border-radius: 3px;
}
QLabel#inspectorPropertyName {
    color: #78879a;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#inspectorPropertyValue {
    color: #223a59;
    font-family: "Consolas";
    font-size: 8pt;
    font-weight: 600;
}
QLabel#inspectorAdvancedText {
    color: #52667f;
    background: #f7f9fc;
    border-left: 3px solid #8aa8d2;
    padding: 7px;
    font-family: "Consolas";
    font-size: 8pt;
}
QFrame#readinessRow {
    background: #f8fafc;
    border: 1px solid #dee6ef;
    border-radius: 3px;
}
QLabel#readinessName { color: #334a67; font-size: 8pt; font-weight: 700; }
QLabel#readinessDetail { color: #7b899a; font-size: 7pt; }
QLabel#readinessReady, QLabel#readinessMissing, QLabel#readinessError,
QLabel#readinessWaiting {
    border-radius: 3px;
    padding: 2px 5px;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#readinessReady { color: #2e7048; background: #e4f4ea; }
QLabel#readinessMissing { color: #926117; background: #fff1cf; }
QLabel#readinessError { color: #a42f36; background: #fde7e8; }
QLabel#readinessWaiting { color: #69778a; background: #eceff3; }
QSplitter#resultWorkspaceSplitter::handle,
QSplitter#resultCenterSplitter::handle { background: #d7e0ea; }
QSplitter#workspaceSplitter::handle { background: #dce3eb; width: 1px; }
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #d8dde4;
    color: #6a7888;
    font-size: 8pt;
}
"""


def apply_application_theme(application: QApplication) -> None:
    application.setStyle("Fusion")
    application.setFont(QFont("Malgun Gothic", 9))
    application.setStyleSheet(APPLICATION_STYLE)
