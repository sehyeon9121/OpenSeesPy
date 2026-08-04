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
