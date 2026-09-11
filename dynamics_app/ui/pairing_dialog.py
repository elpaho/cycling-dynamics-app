from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel,
)
from PyQt6.QtCore import Qt

from ant.hr_receiver import HeartRateScanner


class HRPairingDialog(QDialog):
    """Skenira ANT+ HR uređaje ~6s i pušta usera da odabere pravi ako ih ima više."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pair heart rate monitor")
        self.setMinimumWidth(320)
        self.selected_device_id = None

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Scanning for HR devices...")
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

        self.scanner = HeartRateScanner(duration_s=6.0)
        self.scanner.device_found.connect(self._on_device_found)
        self.scanner.scan_finished.connect(self._on_scan_finished)
        self.scanner.error.connect(self._on_error)
        self.scanner.start()

    def _on_device_found(self, device_id: int):
        item = QListWidgetItem(f"HR device {device_id}")
        item.setData(Qt.ItemDataRole.UserRole, device_id)
        self.list_widget.addItem(item)
        if self.list_widget.count() == 1:
            self.list_widget.setCurrentRow(0)  # prvi nadjeni je default odabir

    def _on_scan_finished(self):
        if self.list_widget.count() == 0:
            self.status_label.setText("No HR devices found. Move closer or check the strap is worn/wet.")
        else:
            self.status_label.setText(f"Found {self.list_widget.count()} device(s). Pick one:")

    def _on_error(self, message: str):
        self.status_label.setText(f"Scan error: {message}")

    def _on_connect(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        self.selected_device_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.accept()

    def closeEvent(self, event):
        self.scanner.stop()
        super().closeEvent(event)

    def reject(self):
        self.scanner.stop()
        super().reject()
