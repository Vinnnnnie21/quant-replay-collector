from __future__ import annotations

from PySide6 import QtCore, QtWidgets

try:
    from i18n import tr
    from research.setups import (
        CreateSetup,
        CreateSetupVersion,
        DecisionProtocol,
        Setup,
        SetupDirection,
        SetupLibrary,
        SetupPersistenceError,
        SetupValidationError,
        SetupVersion,
        SetupVersionSpec,
        SetupWithVersion,
        TimeframeProfile,
        ordered_supported_timeframes,
        recommend_timeframe_profile,
    )
    from ui_style import SPACING, WORKSPACE_SIZES
except ImportError:  # pragma: no cover - package import path
    from ..i18n import tr
    from ..research.setups import (
        CreateSetup,
        CreateSetupVersion,
        DecisionProtocol,
        Setup,
        SetupDirection,
        SetupLibrary,
        SetupPersistenceError,
        SetupValidationError,
        SetupVersion,
        SetupVersionSpec,
        SetupWithVersion,
        TimeframeProfile,
        ordered_supported_timeframes,
        recommend_timeframe_profile,
    )
    from ..ui_style import SPACING, WORKSPACE_SIZES


class SetupEditorForm(QtWidgets.QWidget):
    """Create one Setup and its first immutable version through the domain API."""

    saved = QtCore.Signal(object)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        *,
        setup_library: SetupLibrary,
        language: str = "zh_CN",
        setup: Setup | None = None,
        based_on_version: SetupVersion | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setup_library = setup_library
        self.language = language
        self.setup = setup
        self.based_on_version = based_on_version
        if (setup is None) is not (based_on_version is None):
            raise ValueError(
                "setup and based_on_version must be provided together"
            )
        if (
            setup is not None
            and based_on_version is not None
            and setup.setup_id != based_on_version.setup_id
        ):
            raise ValueError("Setup version does not belong to Setup")
        self.savedSetup: SetupWithVersion | None = None
        self.savedVersion: SetupVersion | None = None
        self._build_ui()
        self.retranslate_ui(language)
        self._apply_recommendation()
        if setup is not None and based_on_version is not None:
            self._load_version(setup, based_on_version)

    def _tr(self, key: str) -> str:
        return tr(key, self.language)

    def _build_ui(self) -> None:
        layout = QtWidgets.QFormLayout(self)
        layout.setContentsMargins(
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
            SPACING["md"],
        )
        layout.setHorizontalSpacing(SPACING["md"])
        layout.setVerticalSpacing(SPACING["sm"])
        layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )
        layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)

        self.displayNameEdit = QtWidgets.QLineEdit()
        self.displayNameEdit.setProperty("role", "searchInput")
        self.directionBox = QtWidgets.QComboBox()
        for direction in SetupDirection:
            self.directionBox.addItem("", direction)
        self.protocolBox = QtWidgets.QComboBox()
        for protocol in DecisionProtocol:
            self.protocolBox.addItem("", protocol)
        self.rulesEdit = QtWidgets.QPlainTextEdit()
        self.rulesEdit.setTabChangesFocus(True)
        self.rulesEdit.setMinimumHeight(
            WORKSPACE_SIZES["setup_rules_min_height"]
        )
        self.rulesEdit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred,
        )

        intervals = ordered_supported_timeframes()
        self.decisionTimeframeBox = QtWidgets.QComboBox()
        self.contextTimeframeOneBox = QtWidgets.QComboBox()
        self.contextTimeframeTwoBox = QtWidgets.QComboBox()
        for combo in (
            self.decisionTimeframeBox,
            self.contextTimeframeOneBox,
            self.contextTimeframeTwoBox,
        ):
            combo.addItems(intervals)

        self.saveButton = QtWidgets.QPushButton()
        self.saveButton.setProperty("role", "primaryButton")
        self.saveButton.clicked.connect(self.save)
        self.cancelButton = QtWidgets.QPushButton()
        self.cancelButton.setProperty("role", "secondaryButton")
        self.cancelButton.clicked.connect(self.cancelled.emit)
        actions = QtWidgets.QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.cancelButton)
        actions.addWidget(self.saveButton)
        layout.addRow(actions)

        self.fieldLabels: dict[str, QtWidgets.QLabel] = {}
        for field, control in (
            ("name", self.displayNameEdit),
            ("direction", self.directionBox),
            ("protocol", self.protocolBox),
            ("rules", self.rulesEdit),
            ("decision_timeframe", self.decisionTimeframeBox),
            ("context_timeframe_one", self.contextTimeframeOneBox),
            ("context_timeframe_two", self.contextTimeframeTwoBox),
        ):
            label = QtWidgets.QLabel()
            self.fieldLabels[field] = label
            layout.addRow(label, control)

        self.errorLabel = QtWidgets.QLabel()
        self.errorLabel.setProperty("role", "pillWarning")
        self.errorLabel.setWordWrap(True)
        self.errorLabel.hide()
        layout.addRow(self.errorLabel)
        self.decisionTimeframeBox.currentTextChanged.connect(
            self._apply_recommendation
        )

    def _apply_recommendation(self, _interval: str | None = None) -> None:
        try:
            profile = recommend_timeframe_profile(
                self.decisionTimeframeBox.currentText()
            )
        except SetupValidationError:
            return
        blockers = (
            QtCore.QSignalBlocker(self.contextTimeframeOneBox),
            QtCore.QSignalBlocker(self.contextTimeframeTwoBox),
        )
        self.contextTimeframeOneBox.setCurrentText(profile.context_one)
        self.contextTimeframeTwoBox.setCurrentText(profile.context_two)
        del blockers

    def save(self) -> None:
        self.errorLabel.hide()
        try:
            spec = SetupVersionSpec(
                direction=self.directionBox.currentData(),
                decision_protocol=self.protocolBox.currentData(),
                decision_rules=self.rulesEdit.toPlainText(),
                timeframes=TimeframeProfile(
                    self.decisionTimeframeBox.currentText(),
                    self.contextTimeframeOneBox.currentText(),
                    self.contextTimeframeTwoBox.currentText(),
                )
            )
            if self.setup is None or self.based_on_version is None:
                created = self.setup_library.create_setup(
                    CreateSetup(
                        display_name=self.displayNameEdit.text(),
                        version=spec,
                    )
                )
            else:
                created = self.setup_library.create_version(
                    CreateSetupVersion(
                        setup_id=self.setup.setup_id,
                        based_on_version_id=(
                            self.based_on_version.setup_version_id
                        ),
                        version=spec,
                    )
                )
        except SetupValidationError as exc:
            self._show_error(exc.code.value, exc.detail)
            return
        except SetupPersistenceError as exc:
            self._show_error(exc.code.value, str(exc))
            return
        if isinstance(created, SetupWithVersion):
            self.savedSetup = created
        else:
            self.savedVersion = created
        self.saved.emit(created)

    def _load_version(
        self,
        setup: Setup,
        version: SetupVersion,
    ) -> None:
        self.displayNameEdit.setText(setup.display_name)
        self.displayNameEdit.setEnabled(False)
        self.directionBox.setCurrentIndex(
            self.directionBox.findData(version.direction)
        )
        self.protocolBox.setCurrentIndex(
            self.protocolBox.findData(version.decision_protocol)
        )
        self.rulesEdit.setPlainText(version.decision_rules)
        self.decisionTimeframeBox.setCurrentText(
            version.timeframes.decision
        )
        self.contextTimeframeOneBox.setCurrentText(
            version.timeframes.context_one
        )
        self.contextTimeframeTwoBox.setCurrentText(
            version.timeframes.context_two
        )

    def _show_error(self, code: str, detail: str) -> None:
        key = f"decision_research.setup.error.{code}"
        localized = self._tr(key)
        self.errorLabel.setText(
            detail if localized == key else localized
        )
        self.errorLabel.show()

    def retranslate_ui(self, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        for field, label in self.fieldLabels.items():
            label.setText(
                self._tr(f"decision_research.setup.field.{field}")
            )
        for index, direction in enumerate(SetupDirection):
            self.directionBox.setItemText(
                index,
                self._tr(
                    f"decision_research.direction.{direction.value.lower()}"
                ),
            )
        for index, protocol in enumerate(DecisionProtocol):
            self.protocolBox.setItemText(
                index,
                self._tr(
                    "decision_research.setup.protocol."
                    f"{protocol.value.lower()}"
                ),
            )
        action = (
            "create"
            if self.based_on_version is None
            else "create_version"
        )
        self.saveButton.setText(
            self._tr(f"decision_research.setup.action.{action}")
        )
        self.cancelButton.setText(self._tr("cancel"))


__all__ = ["SetupEditorForm"]
