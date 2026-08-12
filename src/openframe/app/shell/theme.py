"""Application shell theme shared by all feature presentation components."""

from PySide6.QtGui import QFont, QFontDatabase
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
QPushButton#brandMark {
    min-width: 30px;
    min-height: 30px;
    max-width: 30px;
    max-height: 30px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: #ffffff;
    font-weight: 700;
    padding: 0;
}
QPushButton#brandMark:hover {
    background: #e7ecf3;
}
QPushButton#brandMark:pressed {
    background: #d7dee8;
}
QPushButton#brandName {
    font-size: 12pt;
    font-weight: 700;
    color: #14213d;
    background: transparent;
    border: 0;
    padding: 0;
}
QPushButton#brandName:hover { color: #1e40af; }
QLabel#readyBadge {
    color: #54705f;
    font-size: 8pt;
    padding-left: 8px;
}
QLabel#welcomeHeaderLabel {
    color: #6f7f93;
    font-size: 9pt;
    font-weight: 600;
    padding-left: 8px;
}
QPushButton#uploadButton, QPushButton#runButton {
    min-height: 30px;
    border-radius: 4px;
    padding: 0 12px;
    font-weight: 600;
}
QPushButton#homeButton {
    min-height: 26px;
    border: 0;
    border-left: 1px solid #d8dde4;
    padding: 0 7px;
    color: #607188;
    background: transparent;
    font-size: 7pt;
    font-weight: 700;
}
QPushButton#homeButton:hover {
    color: #174ea6;
    background: #f5f8fc;
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
QPushButton#saveProjectButton {
    min-height: 30px;
    border-radius: 4px;
    padding: 0 12px;
    font-weight: 600;
    background: #ffffff;
    border: 1px solid #bdc8d5;
    color: #2d4059;
}
QPushButton#saveProjectButton:hover { background: #f3f6fa; }
QPushButton#headerIconButton {
    min-width: 26px;
    min-height: 26px;
    max-width: 26px;
    max-height: 26px;
    border: 1px solid #d8dde4;
    border-radius: 13px;
    background: #ffffff;
    color: #607188;
    padding: 0;
}
QPushButton#headerIconButton:hover { background: #f3f6fa; color: #174ea6; }
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
QFrame#startWorkspace {
    background: #f4f7fb;
}
QDialog#analysisProgressDialog {
    background: #ffffff;
}
QLabel#analysisProgressTitle {
    color: #26364a;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#analysisProgressDetail {
    color: #667085;
    background: #f5f7fc;
    border-radius: 4px;
    padding: 0 14px;
    font-family: "Consolas";
    font-size: 9pt;
}
QProgressBar#analysisProgressBar {
    min-height: 6px;
    max-height: 6px;
    background: #dbe7f8;
    border: 0;
    border-radius: 3px;
}
QProgressBar#analysisProgressBar::chunk {
    border-radius: 3px;
    background: #2f80ed;
}
QFrame#startHero {
    background: #eaf1fb;
    border: 1px solid #cfdbeb;
    border-radius: 7px;
}
QLabel#startHeroEyebrow, QLabel#startSectionTitle, QLabel#startFooterTitle {
    color: #58708f;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#startHeroTitle {
    color: #142b49;
    font-size: 19pt;
    font-weight: 700;
}
QLabel#startHeroDescription {
    color: #5f7187;
    font-size: 9pt;
}
QLabel#startSectionHint, QLabel#startFooterText {
    color: #8794a4;
    font-size: 8pt;
}
QFrame#startPrimaryCard, QFrame#startOptionCard {
    background: #ffffff;
    border: 1px solid #d8e1ec;
    border-radius: 6px;
}
QFrame#startPrimaryCard {
    border: 1px solid #9ebbe3;
}
QLabel#startPrimaryIcon, QLabel#startOptionIcon {
    min-width: 30px;
    min-height: 30px;
    max-width: 30px;
    max-height: 30px;
    border-radius: 5px;
    background: #eef2f7;
    color: #53677f;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#startPrimaryIcon {
    background: #174ea6;
    color: #ffffff;
    font-size: 14pt;
}
QLabel#startPrimaryBadge, QLabel#startOptionBadge {
    border-radius: 3px;
    padding: 2px 6px;
    background: #eef2f7;
    color: #718196;
    font-size: 6pt;
    font-weight: 700;
}
QLabel#startPrimaryBadge {
    background: #e7effb;
    color: #174ea6;
}
QLabel#startCardTitle {
    color: #1a304d;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#startCardDescription {
    color: #708095;
    font-size: 8pt;
}
QPushButton#startPrimaryButton, QPushButton#startSecondaryButton {
    min-height: 27px;
    border-radius: 3px;
    padding: 0 10px;
    font-size: 7pt;
    font-weight: 700;
}
QPushButton#startPrimaryButton {
    color: #ffffff;
    background: #174ea6;
    border: 1px solid #174ea6;
}
QPushButton#startPrimaryButton:hover {
    background: #123f89;
}
QPushButton#startSecondaryButton {
    color: #29415f;
    background: #ffffff;
    border: 1px solid #bcc9d8;
}
QPushButton#startSecondaryButton:hover {
    color: #174ea6;
    background: #f3f7fc;
    border-color: #96add0;
}
QPushButton#startInlineButton {
    min-height: 24px;
    padding: 0 8px;
    color: #174ea6;
    background: #f5f8fc;
    border: 1px solid #b8c9df;
    border-radius: 3px;
    font-size: 7pt;
    font-weight: 700;
}
QPushButton#startInlineButton:hover {
    background: #e9f0fb;
    border-color: #8facd2;
}
QFrame#startFooterPanel {
    background: #ffffff;
    border: 1px solid #dce4ed;
    border-radius: 5px;
}
QFrame#startFooterDivider {
    color: #dce4ed;
}
QLabel#startWorkflowSteps {
    color: #36577f;
    font-size: 8pt;
    font-weight: 600;
}
/* Large-format home workspace. These rules intentionally override the legacy
   start-card sizes above while keeping their shared colors and hover states. */
QFrame#startWorkspace { background: #f5f7fb; }
QLabel#startPageTitle {
    color: #10284b;
    font-size: 23pt;
    font-weight: 700;
}
QLabel#startPageDescription {
    color: #66778d;
    font-size: 10pt;
}
QLabel#startColumnTitle {
    color: #172f51;
    font-size: 13pt;
    font-weight: 700;
}
QLabel#startSectionHint, QLabel#startFooterText {
    color: #748397;
    font-size: 9pt;
}
QLabel#startFooterTitle {
    color: #58708f;
    font-size: 8pt;
    font-weight: 700;
}
QFrame#startActionPanel, QFrame#startSessionPanel, QFrame#startWorkflowPanel {
    background: #ffffff;
    border: 1px solid #d5deea;
    border-radius: 7px;
}
QFrame#startContinueColumn { background: transparent; }
QLabel#startPrimaryIcon, QLabel#startOptionIcon {
    min-width: 42px;
    min-height: 42px;
    max-width: 42px;
    max-height: 42px;
    font-size: 10pt;
}
QLabel#startPrimaryIcon { font-size: 17pt; }
QLabel#startCardTitle { font-size: 12pt; }
QLabel#startCardDescription { font-size: 9pt; }
QPushButton#startPrimaryButton, QPushButton#startSecondaryButton {
    min-width: 82px;
    min-height: 36px;
    border-radius: 4px;
    padding: 0 12px;
    font-size: 9pt;
}
QLabel#startSessionName {
    color: #132a49;
    font-size: 18pt;
    font-weight: 700;
}
QPushButton#startResumeButton {
    min-height: 40px;
    padding: 0 18px;
    color: #ffffff;
    background: #174ea6;
    border: 1px solid #174ea6;
    border-radius: 4px;
    font-size: 9pt;
    font-weight: 700;
}
QPushButton#startResumeButton:hover { background: #123f89; }
QFrame#startSessionRow {
    background: #f8fafd;
    border: 1px solid #dce4ef;
    border-radius: 5px;
}
QLabel#startSessionRowName {
    color: #152d4d;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#startSessionRowDetail {
    color: #748397;
    font-size: 8pt;
}
QPushButton#startSessionReturnButton {
    min-width: 78px;
    min-height: 34px;
    padding: 0 10px;
    color: #174ea6;
    background: #ffffff;
    border: 1px solid #aebfda;
    border-radius: 4px;
    font-size: 8pt;
    font-weight: 700;
}
QPushButton#startSessionReturnButton:hover {
    color: #ffffff;
    background: #174ea6;
    border-color: #174ea6;
}
QFrame#startWorkflowStep {
    background: #f6f8fc;
    border: 1px solid #dde5ef;
    border-radius: 5px;
}
QLabel#startStepNumber {
    color: #174ea6;
    font-size: 13pt;
    font-weight: 700;
}
QLabel#startStepName {
    color: #344a66;
    font-size: 9pt;
    font-weight: 700;
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
QPushButton#nonlinearSettingsButton, QPushButton#filterSettingsButton {
    min-height: 28px;
    padding: 0 8px;
    color: #174ea6;
    background: #eaf0f8;
    border: 1px solid #b7cbe9;
    border-radius: 3px;
    font-size: 8pt;
    font-weight: 700;
}
QPushButton#nonlinearSettingsButton:hover, QPushButton#filterSettingsButton:hover {
    background: #dbe7f6;
}
QLabel#nonlinearSettingsSummary {
    color: #68778a;
    font-size: 7pt;
    padding-top: 3px;
}
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
QLabel#resultToolbarValue {
    min-height: 25px;
    max-height: 25px;
    min-width: 125px;
    padding: 0 2px;
    font-size: 8pt;
    color: #29405f;
    font-weight: 600;
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
QFrame#resultCanvasHeader, QFrame#resultViewportControls {
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
QPushButton#resultCanvasButton:checked {
    background: #e7effb;
    border-color: #174ea6;
    color: #174ea6;
    font-weight: 700;
}
QGraphicsView#resultGraphicsView { background: #fbfcfe; border: 0; }
QLabel#resultScaleValue { color: #174ea6; font-weight: 700; min-width: 30px; }
QLabel#resultPushoverStat { color: #40536b; font-size: 8pt; font-weight: 600; }
QLabel#resultPushoverStat[status="ok"] { color: #1a7f37; }
QLabel#resultPushoverStat[status="warning"] { color: #b93815; }
QLabel#resultDataTitle { color: #314863; font-size: 8pt; font-weight: 700; }
QComboBox#resultMemberSelector {
    min-height: 24px;
    max-height: 24px;
    padding: 0 6px;
    font-size: 8pt;
}
QTabWidget#resultTablesTabs::pane {
    border: 0;
    border-top: 1px solid #dbe3ec;
}
QTabWidget#resultTablesTabs QTabBar::tab {
    min-width: 74px;
    padding: 6px 8px;
    color: #738195;
    background: #f6f8fb;
    border-bottom: 2px solid transparent;
}
QTabWidget#resultTablesTabs QTabBar::tab:selected {
    color: #174ea6;
    background: #ffffff;
    border-bottom-color: #174ea6;
    font-weight: 700;
}
QFrame#resultTablesPanel { background: #ffffff; }
QFrame#resultTablesHeader {
    background: #f6f8fb;
    border-bottom: 1px solid #dbe3ec;
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
QTableWidget#resultEndForceTable, QTableWidget#workspaceResultTable,
QTableWidget#resultTablesGrid {
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
QSplitter#resultNormalSplitter::handle { background: #d7e0ea; }
QSplitter#workspaceSplitter::handle { background: #dce3eb; width: 1px; }
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #d8dde4;
    color: #6a7888;
    font-size: 8pt;
}

/* Independent direct-model authoring workspace */
QFrame#directModelWorkspace { background: #f5f7fa; }
QFrame#directModelCommandBar {
    background: #ffffff; border-bottom: 1px solid #d8e0e9;
}
QLabel#directModelBrand {
    color: #0f376d; font-size: 11pt; font-weight: 700; padding-right: 22px;
}
QPushButton#directModelBackButton {
    min-height: 28px; padding: 0 9px; border: 0; background: transparent;
    color: #586b82; font-weight: 600;
}
QPushButton#directModelBackButton:hover { color: #174ea6; background: #eaf0f8; }
QPushButton#directModelOpenButton, QPushButton#directModelSaveButton {
    min-height: 30px; padding: 0 12px; color: #40546d; background: #ffffff;
    border: 1px solid #bdc9d8; border-radius: 6px; font-weight: 600;
}
QPushButton#directModelOpenButton:hover, QPushButton#directModelSaveButton:hover {
    background: #f3f6fa; border-color: #96add0; color: #174ea6;
}
QPushButton#directModelOpenButton:disabled, QPushButton#directModelSaveButton:disabled {
    color: #b6c0cc; background: #f5f7fa; border-color: #e1e7ee;
}
QFrame#modelingWorkflow { background: transparent; }
QToolButton#workflowStep {
    min-height: 28px; padding: 0 10px; border: 0; border-bottom: 2px solid transparent;
    border-radius: 3px; background: transparent; color: #69798c;
    font-size: 9pt; font-weight: 600; text-align: center;
}
QToolButton#workflowStep:hover {
    color: #174ea6; background: #e7eef9;
}
QPushButton#railToolButton {
    min-height: 34px; padding: 0 6px; border: 1px solid #d8e1eb; border-radius: 6px;
    background: #ffffff; color: #35485f; font-weight: 700;
}
QPushButton#railToolButton:hover { background: #f0f5fb; border-color: #b9cadf; }
QPushButton#railToolButton:checked {
    background: #174ea6; border-color: #174ea6; color: #ffffff;
}
QPushButton#railCommandButton {
    min-height: 27px; padding: 0 2px; border: 1px solid #e4e9f0; border-radius: 6px;
    background: #fbfcfe; color: #53657a; font-size: 8pt;
}
QPushButton#railCommandButton:hover { background: #eef3f9; border-color: #b9cadf; color: #174ea6; }
QPushButton#railCommandButton:pressed { background: #e2ecf9; }
QToolButton#supportKindButton {
    min-width: 56px; min-height: 46px; padding: 3px 2px; border: 1px solid #d8e1eb;
    border-radius: 6px; background: #ffffff; color: #35485f; font-size: 8pt;
}
QToolButton#supportKindButton:hover { background: #f0f5fb; border-color: #b9cadf; }
QToolButton#supportKindButton:checked {
    background: #174ea6; border-color: #174ea6; color: #ffffff; font-weight: 700;
}
QPushButton#sectionToggleButton {
    min-height: 24px; padding: 0 4px; border: 0; background: transparent;
    color: #174ea6; font-size: 8pt; font-weight: 700; text-align: left;
}
QPushButton#sectionToggleButton:hover { color: #0f3e82; text-decoration: underline; }
QToolButton#slideOutToggle {
    min-height: 32px; padding: 0 12px; border: 1px solid #d8e1eb; border-radius: 7px;
    background: #ffffff; color: #35485f; font-size: 9pt; font-weight: 600;
}
QToolButton#slideOutToggle:hover { background: #f0f5fb; border-color: #b9cadf; }
QToolButton#slideOutToggle:checked {
    background: #eaf1fb; border-color: #9ebbe3; color: #174ea6;
}
QPushButton#modelingToggleButton {
    min-height: 32px; padding: 0 14px; border: 1px solid #d8e1eb; border-radius: 7px;
    background: #ffffff; color: #35485f; font-size: 9pt; font-weight: 600;
}
QPushButton#modelingToggleButton:hover { background: #f0f5fb; border-color: #b9cadf; }
QPushButton#modelingToggleButton:checked {
    background: #eaf1fb; border-color: #9ebbe3; color: #174ea6;
}
QToolButton#workflowStep:checked {
    color: #ffffff; background: #174ea6;
    border-bottom-color: #0f3e82;
}
QFrame#modelSetupPage, QFrame#workflowPlaceholderPage {
    background: #f5f7fa;
}
QLabel#setupEyebrow {
    color: #174ea6; font-size: 8pt; font-weight: 700;
}
QLabel#setupTitle {
    color: #142b49; font-size: 19pt; font-weight: 700;
}
QLabel#setupDescription {
    color: #68798d; font-size: 9pt;
}
QFrame#setupFormPanel, QFrame#setupSummaryPanel {
    background: #ffffff; border: 1px solid #d8e1eb; border-radius: 6px;
}
QFrame#modelingPropertyPanel { background: #e4e9f0; }
QFrame#propertySectionCard {
    background: #ffffff; border: 1px solid #c9d3e0; border-radius: 8px;
}
QLabel#setupSectionTitle {
    color: #213953; font-size: 10pt; font-weight: 700;
}
QLabel#setupSectionHint, QLabel#setupSummaryHint {
    color: #8290a0; font-size: 8pt;
}
QFrame#setupDivider { color: #e1e7ee; }
QFrame#setupSummaryRow {
    background: #f7f9fc; border: 1px solid #e0e6ed; border-radius: 3px;
}
QLabel#setupSummaryName { color: #718096; font-size: 8pt; }
QLabel#setupSummaryValue { color: #233b58; font-size: 8pt; font-weight: 700; }
QLabel#setupCodeLabel {
    color: #65758a; font-size: 8pt; font-weight: 700; padding-top: 6px;
}
QLabel#setupCommandPreview {
    color: #24476d; background: #eef3f9; border-left: 3px solid #174ea6;
    padding: 10px; font-family: "Consolas"; font-size: 9pt;
}
QLabel#setupNextHint {
    color: #60758e; background: #f6f8fb; padding: 10px;
}
QPushButton#setupContinueButton {
    min-height: 36px; padding: 0 16px; color: #ffffff; background: #174ea6;
    border: 1px solid #174ea6; border-radius: 7px; font-weight: 700;
}
QPushButton#setupContinueButton:hover { background: #123f89; }
QPushButton#setupContinueButton:pressed { background: #0f3574; }
QPushButton#setupContinueButton:disabled {
    color: #aebccd; background: #eef1f6; border-color: #dbe2eb;
}
QLabel#workflowPlaceholderState {
    color: #6e7f92; background: #ffffff; border: 1px dashed #bac7d5;
    border-radius: 5px; padding: 20px;
}
QFrame#materialSettingsPage { background: #f5f7fa; }
QLabel#materialEyebrow { color: #174ea6; font-size: 8pt; font-weight: 700; }
QLabel#materialTitle { color: #142b49; font-size: 17pt; font-weight: 700; }
QLabel#materialDescription { color: #68798d; font-size: 8pt; }
QLabel#materialCountBadge, QLabel#materialIdBadge {
    color: #174ea6; background: #e7effb; border: 1px solid #cad9ef;
    border-radius: 3px; padding: 3px 7px; font-size: 7pt; font-weight: 700;
}
QTabWidget#materialSourceTabs::pane {
    background: #ffffff; border: 1px solid #d8e1eb;
}
QTabWidget#materialSourceTabs QTabBar::tab {
    min-width: 120px; padding: 7px 12px; color: #718096;
    background: #eef2f6; border-bottom: 2px solid transparent;
}
QTabWidget#materialSourceTabs QTabBar::tab:selected {
    color: #174ea6; background: #ffffff; border-bottom-color: #174ea6;
    font-weight: 700;
}
QWidget#materialTabPage { background: #ffffff; }
QFrame#materialBrowserPanel, QFrame#materialEditorPanel, QFrame#kdsEmptyPanel {
    background: #fbfcfe; border: 1px solid #dce4ed; border-radius: 4px;
}
QLabel#materialPanelTitle { color: #263f5d; font-size: 9pt; font-weight: 700; }
QListWidget#kdsMaterialList, QListWidget#userMaterialList {
    background: #ffffff; border: 1px solid #d5dee8; outline: 0;
}
QListWidget#kdsMaterialList::item, QListWidget#userMaterialList::item {
    min-height: 38px; padding: 5px 8px; border-bottom: 1px solid #edf1f5;
}
QListWidget#kdsMaterialList::item:selected, QListWidget#userMaterialList::item:selected {
    color: #174ea6; background: #e7effb;
}
QLabel#kdsEmptyTitle { color: #24415f; font-size: 13pt; font-weight: 700; }
QLabel#kdsEmptyDescription { color: #748397; font-size: 9pt; }
QLabel#kdsRecordCount {
    color: #66788d; background: #eef2f7; border-radius: 3px; padding: 5px 8px;
}
QPushButton#materialPrimaryButton, QPushButton#materialSecondaryButton,
QPushButton#materialDangerButton, QPushButton#materialContinueButton {
    min-height: 30px; padding: 0 11px; border-radius: 3px; font-weight: 600;
}
QPushButton#materialPrimaryButton, QPushButton#materialContinueButton {
    color: #ffffff; background: #174ea6; border: 1px solid #174ea6;
}
QPushButton#materialPrimaryButton:hover, QPushButton#materialContinueButton:hover {
    background: #123f89;
}
QPushButton#materialSecondaryButton {
    color: #334b67; background: #ffffff; border: 1px solid #bdc9d8;
}
QPushButton#materialDangerButton {
    color: #a42f36; background: #ffffff; border: 1px solid #dfb9bc;
}
QLabel#materialValidation { min-height: 20px; font-size: 8pt; }
QLabel#materialValidation[state="error"] {
    color: #a42f36; background: #fde7e8; padding: 4px 7px;
}
QLabel#materialValidation[state="saved"] { color: #28724a; }
QFrame#shearSettingsPanel {
    background: #ffffff; border: 1px solid #d8e1eb; border-radius: 4px;
}
QLabel#materialSectionHint, QLabel#materialFooterHint {
    color: #7a899b; font-size: 8pt;
}
QDoubleSpinBox {
    min-height: 29px; background: #ffffff; border: 1px solid #cfd8e3;
    border-radius: 3px; padding: 0 7px;
}
QSplitter#materialEditorSplitter::handle { background: #d8e1eb; width: 1px; }

/* Refined material editor */
QFrame#materialSettingsPage { background: #ffffff; }
QTabWidget#materialSourceTabs::pane {
    border: 0; border-top: 1px solid #d5deea; background: #ffffff;
}
QTabWidget#materialSourceTabs QTabBar::tab {
    min-width: 122px; min-height: 34px; padding: 0 12px;
    background: #f1f4f8; color: #6f7f91; border: 0;
    border-bottom: 2px solid transparent;
}
QTabWidget#materialSourceTabs QTabBar::tab:selected {
    color: #174ea6; background: #ffffff; border-bottom-color: #174ea6;
}
QFrame#materialBrowserPanel {
    background: #f8faff; border: 0; border-right: 1px solid #d5deea; border-radius: 0;
}
QFrame#materialEditorPanel, QFrame#kdsEmptyPanel {
    background: #ffffff; border: 0; border-radius: 0;
}
QLabel#materialEditorTitle { color: #102d54; font-size: 11pt; font-weight: 700; }
QLabel#materialIdBadge {
    color: #49627f; background: #eef2f7; border: 0;
    padding: 3px 7px; font-size: 8pt; font-weight: 600;
}
QPushButton#materialListAddButton {
    min-height: 28px; padding: 0 9px; color: #294a70; background: #ffffff;
    border: 1px solid #c4cfdd; border-radius: 3px; font-weight: 600;
}
QLineEdit, QComboBox, QDoubleSpinBox {
    min-height: 34px; max-height: 34px;
}
QListWidget#userMaterialList::item {
    min-height: 48px; padding: 7px 9px; border-bottom: 1px solid #e5eaf0;
}
QListWidget#userMaterialList::item:selected {
    color: #174ea6; background: #e3ebff; border: 1px solid #5b7ee5;
}
QFrame#materialPropertyGroup {
    background: #f8faff; border: 1px solid #d4ddea; border-radius: 2px;
}
QLabel#materialPropertyGroupTitle {
    min-height: 31px; padding: 0 10px; color: #173657;
    background: #e9f0fb; border-bottom: 1px solid #d0dae7;
    font-size: 9pt; font-weight: 700;
}
QLabel#materialFieldLabel {
    min-width: 142px; color: #233b59; font-size: 8pt; font-weight: 600;
}
QLabel#materialUnitLabel {
    min-width: 48px; color: #5f7187; font-family: "Consolas"; font-size: 8pt;
}
QLabel#materialFilterLabel {
    color: #66788d; font-size: 7pt; font-weight: 700; padding-top: 3px;
}
QLineEdit#derivedMaterialValue {
    color: #53647a; background: #eef2f7; border: 1px solid #d7dee7;
}
QFrame#shearSettingsPanel {
    background: #ffffff; border: 0; border-top: 1px solid #d7dfe8; border-radius: 0;
}
QFrame#materialFooter {
    min-height: 42px; max-height: 42px; background: #ffffff;
    border-top: 1px solid #d5deea;
}
QPushButton#materialContinueButton { min-height: 30px; }
QSplitter#materialEditorSplitter::handle { width: 1px; background: #d5deea; }

/* Menu bar */
QMenuBar {
    background: #f8f9fa;
    border-top: 1px solid #d8dde4;
    border-bottom: 1px solid #d8dde4;
    min-height: 31px;
    max-height: 31px;
    padding: 0;
    color: #3c4a5e;
    font-size: 8pt;
}
QMenuBar::item {
    padding: 0 7px;
    margin: 0;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 0;
}
QMenuBar::item:selected {
    background: #eef0ff;
    color: #00288e;
    border: 1px solid #00288e;
}
QMenuBar::item:pressed {
    background: #eef0ff;
    color: #00288e;
    border: 1px solid #00288e;
}
QMenu {
    background: #ffffff;
    border: 1px solid #d8dde4;
    padding: 4px;
}
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 3px; font-size: 8pt; }
QMenu::item:selected { background: #eef2f7; color: #174ea6; }
QMenu::item:disabled { color: #b3bdca; }
QMenu::separator { height: 1px; background: #e5e9ee; margin: 4px 6px; }

/* Breadcrumb / project bar, prepended to the section tabs */
QFrame#navigationBreadcrumb { background: transparent; }
QLabel#breadcrumbIcon { color: #8a97a6; font-size: 9pt; }
QLabel#breadcrumbName { color: #2d4059; font-size: 8pt; font-weight: 600; }
QLabel#breadcrumbStatus {
    color: #2e7048;
    font-size: 7pt;
    font-weight: 700;
    padding: 1px 7px;
    border-radius: 8px;
    background: #e4f4ea;
}
QFrame#navigationDivider { background: #dce3eb; max-width: 1px; min-width: 1px; }

QFrame#modelWorkspacePage { background: #f5f7fa; }

/* Reusable page header (MODEL workspace wrapper, SETUP page) */
QFrame#pageHeader {
    background: #ffffff;
    border-bottom: 1px solid #d8dde4;
}
QLabel#pageTitle { color: #142b49; font-size: 13pt; font-weight: 700; }
QLabel#pageSubtitle { color: #778193; font-size: 8pt; }
QPushButton#pageActionButton {
    border: 0;
    background: transparent;
    color: #174ea6;
    font-size: 8pt;
    font-weight: 700;
    padding: 0 4px;
}
QPushButton#pageActionButton:hover { text-decoration: underline; }
QLabel#pageStatusBadge {
    border-radius: 9px;
    padding: 3px 10px;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#pageStatusBadge[state="ready"] { color: #2e7048; background: #e4f4ea; }
QLabel#pageStatusBadge[state="running"] { color: #925c1a; background: #fff1cf; }
QLabel#pageStatusBadge[state="error"] { color: #a42f36; background: #fde7e8; }

QPushButton#openSetupButton {
    min-height: 36px;
    margin-top: 6px;
    border-radius: 4px;
    color: #ffffff;
    background: #174ea6;
    border: 1px solid #174ea6;
    font-weight: 700;
}
QPushButton#openSetupButton:hover { background: #123f89; }

/* SETUP pre-check chips */
QFrame#precheckRow { background: #ffffff; border-top: 1px solid #dce3eb; }
QLabel#precheckChip {
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#precheckChip[state="ok"] { color: #2e7048; background: #e4f4ea; }
QLabel#precheckChip[state="warn"] { color: #926117; background: #fff1cf; }
QLabel#precheckChip[state="error"] { color: #a42f36; background: #fde7e8; }
QLabel#precheckSummary { color: #7b899a; font-size: 8pt; }
QLabel#precheckSummary[state="warn"] { color: #926117; font-weight: 600; }
QLabel#precheckSummary[state="error"] { color: #a42f36; font-weight: 600; }

/* SETUP's ANALYSIS FLOW list */
QFrame#setupFlowPanel { background: #f8fafc; border-right: 1px solid #dce3eb; }
QListWidget#setupFlowList {
    background: transparent;
    border: 0;
    outline: 0;
    padding: 6px;
}
QListWidget#setupFlowList::item {
    min-height: 30px;
    padding: 0 8px;
    margin: 1px 0;
    border-radius: 4px;
    color: #5c6b7f;
    font-size: 8pt;
}
QFrame#setupCenterColumn { background: #eef2f6; }
QFrame#setupGuidePanel { background: #f8fafc; border-left: 1px solid #dce3eb; }

/* Stitch project hub — compact engineering launcher. */
QFrame#startWorkspace { background: #ffffff; }
QFrame#startContent { background: transparent; }
QFrame#startHubHeader {
    background: transparent;
    border-bottom: 1px solid #c4c5d5;
}
QLabel#startPageTitle {
    color: #191c1d;
    font-size: 16pt;
    font-weight: 600;
}
QLabel#startPageDescription {
    color: #555f6d;
    font-size: 10pt;
}
QLabel#startSectionHeading {
    color: #555f6d;
    font-size: 9pt;
    font-weight: 700;
}
QFrame#startColumn, QFrame#startContinueColumn, QFrame#startWorkflowWrapper {
    background: transparent;
}
QFrame#startActionPanel, QFrame#startSessionPanel, QFrame#startWorkflowPanel {
    background: #f8f9fa;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QFrame#startActionRow {
    background: #f8f9fa;
    border: 0;
    border-bottom: 1px solid #c4c5d5;
}
QFrame#startActionRow[last="true"] {
    background: #f3f4f5;
    border-bottom: 0;
}
QLabel#startActionIcon {
    min-width: 46px;
    min-height: 46px;
    max-width: 46px;
    max-height: 46px;
    color: #00288e;
    background: #edeeef;
    border: 1px solid #c4c5d5;
    border-radius: 3px;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 10pt;
    font-weight: 700;
}
QLabel#startCardTitle {
    color: #191c1d;
    font-size: 11pt;
    font-weight: 600;
}
QLabel#startCardDescription {
    color: #555f6d;
    font-size: 9pt;
}
QPushButton#startActionButton {
    min-width: 78px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 12px;
    color: #555f6d;
    background: #ffffff;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
    font-size: 9pt;
    font-weight: 600;
}
QPushButton#startActionButton:hover {
    color: #00288e;
    background: #edeeef;
    border-color: #00288e;
}
QPushButton#startActionButton[primary="true"] { color: #00288e; }
QFrame#startSessionRow {
    background: #f8f9fa;
    border: 0;
    border-bottom: 1px solid #c4c5d5;
    border-radius: 0;
}
QFrame#startSessionRow[active="true"] {
    background: #ffffff;
    border: 2px solid #1e40af;
    border-radius: 2px;
}
QLabel#startCurrentSessionBadge {
    color: #ffffff;
    background: #1e40af;
    border-radius: 2px;
    padding: 2px 6px;
    font-size: 7pt;
    font-weight: 700;
}
QLabel#startSessionRowName {
    color: #191c1d;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 10pt;
    font-weight: 600;
}
QLabel#startSessionRowDetail { color: #555f6d; font-size: 9pt; }
QPushButton#startSessionReturnButton {
    min-width: 78px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 12px;
    color: #ffffff;
    background: #00288e;
    border: 1px solid #00288e;
    border-radius: 2px;
    font-size: 9pt;
    font-weight: 600;
}
QPushButton#startSessionReturnButton:hover { background: #1e40af; }
QFrame#startWorkflowStep {
    background: transparent;
    border: 0;
}
QLabel#startStepName {
    color: #555f6d;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#startStepName[active="true"] { color: #00288e; }
QLabel#startStepDetail { color: #757684; font-size: 8pt; }
QLabel#startWorkflowArrow { color: #c4c5d5; font-size: 13pt; }

/* Stitch shell density and 1 px engineering borders. */
QFrame#appHeader, QFrame#appBrandPanel {
    min-height: 30px;
    max-height: 30px;
    background: #f8f9fa;
    border: 0;
}
QFrame#appBrandPanel {
    border-right: 1px solid #d8dde4;
}
QPushButton#brandName {
    color: #00288e;
    font-size: 18px;
    font-weight: 700;
    background: transparent;
    border: 0;
    padding: 0;
}
QPushButton#brandMark {
    min-width: 22px; min-height: 22px; max-width: 22px; max-height: 22px;
    border-radius: 2px; background: #00288e; font-size: 7pt;
}
QPushButton#uploadButton, QPushButton#runButton, QPushButton#saveProjectButton {
    min-height: 26px; max-height: 26px; border-radius: 2px; padding: 0 13px;
    font-size: 8pt;
}
QPushButton#runButton { background: #00288e; border-color: #00288e; }
QPushButton#runButton:hover { background: #1e40af; }
QPushButton#headerIconButton {
    min-width: 26px; min-height: 26px; max-width: 26px; max-height: 26px;
    border: 0; border-radius: 2px; background: transparent; font-size: 10pt;
}
QFrame#headerActionDivider { color: #c4c5d5; max-width: 1px; }
QFrame#workspaceNavigation { min-height: 36px; max-height: 36px; }
QFrame#workspaceNavigation QToolButton {
    min-width: 80px; min-height: 35px; max-height: 35px;
    border-bottom-width: 2px; color: #555f6d; font-size: 8pt;
}
QFrame#workspaceNavigation QToolButton:checked {
    color: #00288e; background: #eef0ff; border-bottom-color: #00288e;
}
QFrame#pageHeader { background: #f8f9fa; border-bottom-color: #c4c5d5; }
QLabel#pageTitle { color: #191c1d; font-size: 16pt; font-weight: 700; }
QLabel#pageSubtitle { color: #555f6d; font-size: 9pt; }
QPushButton#pageActionButton { color: #00288e; }
QLabel#pageStatusBadge[state="ready"] { color: #006a61; background: #dff7f2; }
QSplitter#workspaceSplitter::handle, QSplitter#setupWorkspaceSplitter::handle {
    background: #c4c5d5; width: 1px;
}
QStatusBar {
    min-height: 22px; max-height: 22px;
    background: #e7e8e9; border-top: 1px solid #c4c5d5;
    color: #555f6d; font-family: "JetBrains Mono", "Consolas"; font-size: 7pt;
}
QStatusBar[mode="model"] {
    background: #2e3132; border-top: 0; color: #f0f1f2;
}
QStatusBar[mode="setup"] { background: #ffffff; color: #555f6d; }

/* Stitch target panel widths and setup density. */
QFrame#modelSidebar { min-width: 260px; max-width: 260px; background: #f8f9fa; }
QFrame#analysisSidebar { min-width: 320px; max-width: 320px; background: #f8f9fa; }
QFrame#modelSidebarSection {
    background: #f8f9fa;
    border-bottom: 1px solid #c4c5d5;
}
QFrame#modelSummaryGrid { background: transparent; border: 0; }
QFrame#modelContentHeader {
    background: #f3f4f5;
    border-bottom: 1px solid #c4c5d5;
}
QLabel#modelContentMenu { color: #757684; font-size: 11pt; }
QFrame#modelSidebar QTreeWidget#modelTree {
    background: #f8f9fa;
    border: 0;
    border-radius: 0;
    padding: 8px;
}
QFrame#setupFlowPanel { min-width: 220px; max-width: 220px; background: #f8f9fa; }
QFrame#setupGuidePanel { min-width: 300px; max-width: 300px; background: #f8f9fa; }
QLabel#setupGuideTopic {
    color: #191c1d;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#setupGuideCallout {
    color: #555f6d;
    background: #f3f4f5;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
    padding: 9px;
    font-size: 8pt;
}
QFrame#setupGuideDivider { color: #c4c5d5; max-height: 1px; }
QLabel#setupGuideReference {
    color: #00288e;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 7pt;
}
QFrame#setupCenterColumn { background: #f3f4f5; }
QListWidget#setupFlowList { padding: 8px; }
QListWidget#setupFlowList::item {
    min-height: 34px; padding: 0 8px; margin: 1px 0; border-radius: 2px;
    color: #555f6d; font-size: 8pt;
}
QPushButton#openSetupButton { min-height: 32px; border-radius: 2px; background: #00288e; }
QFrame#precheckRow { min-height: 56px; max-height: 56px; border-top-color: #c4c5d5; }
QFrame#analysisSettingsPanel { background: #f8f9fa; }
QFrame#analysisSettingsPanel QFrame#rightSection {
    background: #f8f9fa;
    border-bottom: 0;
}
QScrollArea#setupSettingsScroll {
    background: #f8f9fa;
    border: 0;
}
QScrollArea#setupSettingsScroll > QWidget > QWidget { background: #f8f9fa; }
QFrame#setupSettingsSurface { background: #f8f9fa; }
QFrame#setupConfigBar, QFrame#setupConfigCard {
    background: #f8f9fa;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QFrame#setupConfigCard[highlighted="true"] {
    background: #ffffff;
    border: 2px solid #1e40af;
}
QLabel#setupConfigTitle {
    color: #191c1d;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#setupReviewBadge {
    color: #555f6d;
    background: #ffffff;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
    padding: 2px 6px;
    font-size: 6pt;
    font-weight: 700;
}
QFrame#setupBehaviorTile {
    background: #ffffff;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QLabel#setupMetricLabel { color: #555f6d; font-size: 7pt; font-weight: 700; }
QLabel#setupMetricValue {
    color: #191c1d;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 8pt;
    font-weight: 600;
}
QLabel#setupBehaviorValue {
    color: #555f6d; font-family: "JetBrains Mono", "Consolas"; font-size: 8pt;
}
QLabel#setupBehaviorValue[state="ok"] { color: #087f5b; }
QFrame#setupLoadProgress {
    background: transparent;
    border-left: 1px dashed #c4c5d5;
}
QProgressBar#setupLoadProgressBar {
    min-height: 4px;
    max-height: 4px;
    background: #c4c5d5;
    border: 0;
    border-radius: 2px;
}
QProgressBar#setupLoadProgressBar::chunk {
    background: #00288e;
    border-radius: 2px;
}
QLabel#setupProgressCaption {
    color: #757684;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 7pt;
}
QLabel#setupProgressCaption[active="true"] { color: #00288e; }
QLabel#setupNotice {
    color: #555f6d;
    background: #e1e3e4;
    border-left: 2px solid #757684;
    padding: 7px 9px;
    font-size: 8pt;
}
QLabel#setupConvergenceChart {
    color: #00288e;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 11pt;
}
QFrame#setupSolutionFlow {
    background: #f8f9fa;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QFrame#setupSolutionNode {
    background: #ffffff;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QFrame#setupSolutionNode[active="true"] {
    background: #eef0ff;
    border: 2px solid #1e40af;
}
QLabel#setupSolutionSymbol {
    color: #191c1d;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 8pt;
}
QLabel#setupSolutionCaption {
    color: #757684;
    font-size: 6pt;
    font-weight: 700;
}
QLabel#setupSolutionCaption[active="true"] { color: #00288e; }
QLabel#setupSolutionArrow { color: #c4c5d5; font-size: 13pt; }
QFrame#setupConvergenceChart {
    min-height: 62px;
    background: transparent;
    border-bottom: 1px solid #c4c5d5;
}
QFrame#setupConvergenceBar { background: #bdc7d8; border: 0; }
QFrame#setupConvergenceBar[converged="true"] { background: #00288e; }
QFrame#setupConfigBar QComboBox { min-height: 27px; max-height: 27px; }
QFrame#setupConfigCard QComboBox { min-height: 25px; max-height: 25px; }
QFrame#setupConfigCard QPushButton#nonlinearSettingsButton {
    min-height: 27px; padding: 0 10px; border-radius: 2px;
    color: #00288e; background: #ffffff; border: 1px solid #1e40af;
}

/* Direct 2D modeling and student result workspace. The geometry follows the
   Stitch reference while retaining OpenFrame's existing navy/gray palette. */
QFrame#modelingInterfacePage, QWidget#direct2DModelingWorkspace,
QWidget#direct2DResultPage { background: #f3f4f5; }
QFrame#direct2DPageHeader {
    min-height: 58px;
    max-height: 58px;
    background: #f8f9fa;
    border: 0;
    border-bottom: 1px solid #c4c5d5;
}
QStackedWidget#direct2DHeaderControls { background: transparent; }
QLabel#direct2DPageTitle {
    color: #191c1d;
    font-size: 16pt;
    font-weight: 700;
}
QLabel#direct2DPageDescription { color: #555f6d; font-size: 8pt; }
QLabel#direct2DFieldLabel {
    color: #757684;
    font-size: 6pt;
    font-weight: 700;
}
QComboBox#direct2DModelType {
    min-width: 120px;
    min-height: 27px;
    max-height: 27px;
    background: #ffffff;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QLabel#direct2DReadyBadge {
    color: #006a61;
    background: #dff7f2;
    border: 1px solid #addfd7;
    border-radius: 2px;
    padding: 5px 8px;
    font-size: 7pt;
    font-weight: 700;
}
QFrame#direct2DToolRail {
    background: #f8f9fa;
    border: 0;
    border-right: 1px solid #c4c5d5;
}
QFrame#direct2DToolRail QPushButton#railToolButton,
QFrame#direct2DToolRail QPushButton#railFeatureButton {
    min-height: 45px;
    max-height: 45px;
    padding: 0 3px;
    color: #555f6d;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    font-size: 8pt;
    font-weight: 600;
}
QFrame#direct2DToolRail QPushButton#railToolButton:hover,
QFrame#direct2DToolRail QPushButton#railFeatureButton:hover {
    color: #00288e;
    background: #eef0ff;
    border-color: #bdc7d8;
}
QFrame#direct2DToolRail QPushButton#railToolButton:checked {
    color: #ffffff;
    background: #00288e;
    border-color: #00288e;
}
QFrame#direct2DToolRail QPushButton#railCommandButton {
    min-height: 25px;
    max-height: 25px;
    padding: 0 2px;
    color: #757684;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    font-size: 6pt;
}
QFrame#direct2DToolRail QPushButton#railCommandButton:hover {
    color: #00288e;
    background: #eef0ff;
    border-color: #bdc7d8;
}
QFrame#direct2DCanvasPanel {
    background: #ffffff;
    border: 0;
    border-right: 1px solid #c4c5d5;
}
QFrame#direct2DCanvasToolbar {
    min-height: 38px;
    max-height: 38px;
    background: #f8f9fa;
    border: 0;
    border-bottom: 1px solid #c4c5d5;
}
QFrame#direct2DCanvasToolbar QToolButton#slideOutToggle {
    min-height: 26px;
    max-height: 26px;
    padding: 0 9px;
    color: #555f6d;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    font-size: 7pt;
}
QFrame#direct2DCanvasToolbar QToolButton#slideOutToggle:hover,
QFrame#direct2DCanvasToolbar QToolButton#slideOutToggle:checked {
    color: #00288e;
    background: #eef0ff;
    border-color: #1e40af;
}
QScrollArea#modelingInspectorScroll {
    background: #f8f9fa;
    border: 0;
    border-left: 1px solid #c4c5d5;
}
QFrame#modelingPropertyPanel { background: #f8f9fa; }
QLabel#direct2DInspectorTitle {
    color: #191c1d;
    font-size: 9pt;
    font-weight: 700;
}
QFrame#modelingPropertyPanel QFrame#propertySectionCard {
    background: #ffffff;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QStackedWidget#direct2DFooterStack {
    min-height: 42px;
    max-height: 42px;
    background: #ffffff;
}
QFrame#direct2DResultStatusBar {
    background: #ffffff;
    border-top: 1px solid #c4c5d5;
    color: #555f6d;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 7pt;
}
QLabel#direct2DResultCase {
    min-width: 125px;
    color: #555f6d;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 7pt;
}
QPushButton#direct2DSecondaryButton, QPushButton#direct2DPrimaryButton {
    min-height: 30px;
    padding: 0 11px;
    border-radius: 2px;
    font-size: 7pt;
    font-weight: 700;
}
QPushButton#direct2DSecondaryButton {
    color: #00288e;
    background: #ffffff;
    border: 1px solid #1e40af;
}
QPushButton#direct2DPrimaryButton {
    color: #ffffff;
    background: #00288e;
    border: 1px solid #00288e;
}
QFrame#resultsWorkspace[compact2d="true"] { background: #ffffff; }
QFrame#resultTypeSidebar[compact2d="true"] {
    background: #f8f9fa;
    border: 0;
    border-right: 1px solid #c4c5d5;
}
QFrame#resultTypeSidebar[compact2d="true"] QFrame#resultTypeGroup {
    background: transparent;
    border: 0;
    border-radius: 0;
}
QFrame#resultTypeSidebar[compact2d="true"] QLabel#resultTypeGroupCount {
    background: transparent;
    border: 0;
    color: #a3a6ad;
}
QFrame#resultTypeSidebar[compact2d="true"] QToolButton#resultTypeButton {
    min-height: 28px;
    max-height: 28px;
    padding: 0 8px;
    border: 0;
    border-left: 2px solid transparent;
    border-radius: 0;
    background: transparent;
    color: #555f6d;
    text-align: left;
    font-size: 8pt;
}
QFrame#resultTypeSidebar[compact2d="true"] QToolButton#resultTypeButton:checked {
    color: #00288e;
    background: #eef0ff;
    border-left-color: #00288e;
}
QFrame#resultSummaryPanel[compact2d="true"] {
    background: #f8f9fa;
    border: 0;
    border-left: 1px solid #c4c5d5;
}
QFrame#resultSummaryPanel[compact2d="true"] QFrame#resultMetricRow {
    background: #ffffff;
    border: 1px solid #c4c5d5;
    border-radius: 2px;
}
QFrame#resultSummaryPanel[compact2d="true"] QLabel#resultMetricValue {
    color: #00288e;
}
QLabel#direct2DResultLearningHint {
    color: #555f6d;
    background: #eef0ff;
    border-left: 2px solid #1e40af;
    padding: 8px;
    font-size: 8pt;
}
"""


def apply_application_theme(application: QApplication) -> None:
    application.setStyle("Fusion")
    families = set(QFontDatabase.families())
    family = next(
        (name for name in ("Noto Sans", "Segoe UI", "Malgun Gothic") if name in families),
        application.font().family(),
    )
    application.setFont(QFont(family, 9))
    application.setStyleSheet(APPLICATION_STYLE)
