from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel,
)
from PyQt6.QtCore import Qt


class DevicePairingDialog(QDialog):
    """
    Generic scan-and-pick dijalog za bilo koji ANT+ device tip (HR, power meter,
    itd) preko zajednickog AntManager-a. Skenira ~6s, pusta usera da odabere
    ako ih ima vise.
    """

    def __init__(self, title: str, start_scan_fn, stop_scan_fn, found_signal, error_signal, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(320)
        self.selected_device_id = None

        self._stop_scan_fn = stop_scan_fn

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Scanning for devices...")
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.setEnabled(False)
        self.connect_button.clicked.connect(self._on_connect)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.connect_button)
        layout.addLayout(button_row)

        self.list_widget.itemSelectionChanged.connect(
            lambda: self.connect_button.setEnabled(bool(self.list_widget.selectedItems()))
        )
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_connect())

        found_signal.connect(self._on_device_found)
        error_signal.connect(self._on_error)
        start_scan_fn()

        self._stop_timer_id = self.startTimer(6000)  # auto-prekini scan nakon 6s (jednokratno)

    def timerEvent(self, event):
        self.killTimer(self._stop_timer_id)
        self._stop_scan_fn()
        if self.list_widget.count() == 0:
            self.status_label.setText("No devices found. Move closer / check it's broadcasting.")
        else:
            self.status_label.setText(f"Found {self.list_widget.count()} device(s). Pick one:")

    def _on_device_found(self, device_id: int):
        item = QListWidgetItem(f"Device {device_id}")
        item.setData(Qt.ItemDataRole.UserRole, device_id)
        self.list_widget.addItem(item)
        if self.list_widget.count() == 1:
            self.list_widget.setCurrentRow(0)  # prvi nadjeni je default odabir

    def _on_error(self, message: str):
        self.status_label.setText(f"Scan error: {message}")

    def _on_connect(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        self.selected_device_id = items[0].data(Qt.ItemDataRole.UserRole)
        self._stop_scan_fn()
        self.accept()

    def closeEvent(self, event):
        self._stop_scan_fn()
        super().closeEvent(event)

    def reject(self):
        self._stop_scan_fn()
        super().reject()
