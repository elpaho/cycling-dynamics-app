from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QProgressBar, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer

from ant.ant_manager import AntManager

DARK_STYLESHEET = """
    QMainWindow { background: #1a1a1a; }
    QWidget { color: #e0e0e0; }
    QLabel { background: transparent; }
    #card { background: #242424; border: 1px solid #333; border-radius: 8px; }
    #metricCard { background: #242424; border: 1px solid #333; border-radius: 8px; }
    #metricLabel { font-size: 12px; color: #888; }
    #metricValue { font-size: 26px; font-weight: 600; color: #e0e0e0; }
    #panelTitle { font-weight: 600; font-size: 13px; color: #e0e0e0; }
    #rowLabel { color: #888; font-size: 12px; }
    #rowValue { font-size: 13px; color: #e0e0e0; }
    #mutedLabel { color: #888; font-size: 12px; }
    #sessionTimer { font-size: 13px; color: #888; }
    QPushButton { background: #2a2a2a; color: #e0e0e0; border: 1px solid #333; border-radius: 6px; padding: 6px 10px; }
    QPushButton:hover { background: #333; }
    QPushButton:disabled { color: #555; background: #232323; }
    QProgressBar { background: #333; border-radius: 4px; border: none; }
    QProgressBar::chunk { background: #185FA5; border-radius: 4px; }
    QDialog { background: #1a1a1a; color: #e0e0e0; }
    QLineEdit { background: #2a2a2a; color: #e0e0e0; border: 1px solid #333; border-radius: 4px; padding: 4px; }
    QListWidget { background: #242424; color: #e0e0e0; border: 1px solid #333; }
    QListWidget::item:selected { background: #1a3a5c; color: #7ab3e0; }
"""


def _box(title: str) -> tuple[QFrame, QLabel, QLabel]:
    """Kreira jednu 'metric' kućicu (naslov + veliki broj)."""
    frame = QFrame()
    frame.setObjectName("metricCard")
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)

    title_label = QLabel(title)
    title_label.setObjectName("metricLabel")
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    value_label = QLabel("--")
    value_label.setObjectName("metricValue")
    value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(title_label)
    layout.addWidget(value_label)
    return frame, title_label, value_label


class PedalPanel(QFrame):
    """Kartica za jednu pedalu (Left/Right) s cycling dynamics podacima."""

    ROWS = [
        ("Torque eff.", "torque_eff", "%"),
        ("Pedal smooth.", "pedal_smooth", "%"),
        ("PCO", "pco_mm", " mm"),
        ("Power phase", "power_phase", "deg_range"),
        ("Peak phase", "peak_phase", "deg_range"),
    ]

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        title_label = QLabel(title)
        title_label.setObjectName("panelTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        grid = QGridLayout()
        self.value_labels = {}
        for row, (label_text, key, _unit) in enumerate(self.ROWS):
            lbl = QLabel(label_text)
            lbl.setObjectName("rowLabel")
            val = QLabel("--")
            val.setObjectName("rowValue")
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(val, row, 1)
            self.value_labels[key] = val
        layout.addLayout(grid)
        self.setEnabled(False)  # dok nema dual-side podataka

    def update_data(self, data: dict):
        self.setEnabled(True)
        for _label, key, unit in self.ROWS:
            v = data.get(key)
            if v is None:
                continue
            if unit == "deg_range":
                self.value_labels[key].setText(f"{v[0]}\u00b0\u2013{v[1]}\u00b0")
            else:
                self.value_labels[key].setText(f"{v}{unit}")

    def clear_data(self):
        self.setEnabled(False)
        for lbl in self.value_labels.values():
            lbl.setText("--")


class RunningAverage:
    """Prosti sum/count akumulator za jedno numeričko polje."""

    def __init__(self):
        self.total = 0.0
        self.count = 0

    def add(self, value):
        if value is None:
            return
        self.total += value
        self.count += 1

    @property
    def avg(self):
        return self.total / self.count if self.count else None

    def reset(self):
        self.total = 0.0
        self.count = 0


DYNAMICS_SCALAR_KEYS = ["torque_eff", "pedal_smooth", "pco_mm"]
DYNAMICS_RANGE_KEYS = ["power_phase", "peak_phase"]  # svaki je (start, end) tuple


def _new_dynamics_accumulators() -> dict:
    acc = {key: RunningAverage() for key in DYNAMICS_SCALAR_KEYS}
    for key in DYNAMICS_RANGE_KEYS:
        acc[f"{key}_start"] = RunningAverage()
        acc[f"{key}_end"] = RunningAverage()
    return acc


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cycling Dynamics")
        self.resize(560, 720)

        self.session_active = False
        self.frozen = False
        self.session_seconds = 0
        self.session_start_time = None

        self._build_ui()
        self._init_accumulators()
        self._start_data_sources()

        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self._on_session_tick)

    # ---------------------------------------------------------- UI setup
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)

        # --- pairing status row ---
        pairing_row = QHBoxLayout()
        self.power_status = QPushButton("Power: initializing...")
        self.power_status.setEnabled(False)
        self.power_status.clicked.connect(self._retry_power)
        self.hr_status = QPushButton("HR: initializing...")
        self.hr_status.setEnabled(False)
        self.hr_status.clicked.connect(self._retry_hr)
        pairing_row.addWidget(self.power_status)
        pairing_row.addWidget(self.hr_status)
        root.addLayout(pairing_row)

        # --- metric boxes: power / cadence / hr ---
        metrics_row = QHBoxLayout()
        self.power_box, _, self.power_value = _box("Power")
        self.cadence_box, _, self.cadence_value = _box("Cadence")
        self.hr_box, _, self.hr_value = _box("Heart rate")
        for box in (self.power_box, self.cadence_box, self.hr_box):
            metrics_row.addWidget(box)
        root.addLayout(metrics_row)

        # --- power balance ---
        balance_frame = QFrame()
        balance_frame.setObjectName("card")
        balance_frame.setFrameShape(QFrame.Shape.StyledPanel)
        balance_layout = QVBoxLayout(balance_frame)
        header = QHBoxLayout()
        left_hdr = QLabel("Power balance")
        left_hdr.setObjectName("mutedLabel")
        self.balance_value = QLabel("--% / --%")
        self.balance_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.balance_value.setStyleSheet("font-size: 22px; font-weight: 600; color: #e0e0e0;")
        self.balance_avg = QLabel("avg --% / --%")
        self.balance_avg.setObjectName("mutedLabel")
        header.addWidget(left_hdr)
        header.addStretch()
        header.addWidget(self.balance_avg)
        balance_layout.addLayout(header)
        balance_layout.addWidget(self.balance_value)
        self.balance_bar = QProgressBar()
        self.balance_bar.setRange(0, 100)
        self.balance_bar.setValue(50)
        self.balance_bar.setTextVisible(False)
        self.balance_bar.setFixedHeight(8)
        balance_layout.addWidget(self.balance_bar)
        root.addWidget(balance_frame)

        # --- L/R pedal panels ---
        pedals_row = QHBoxLayout()
        self.left_panel = PedalPanel("Left pedal")
        self.right_panel = PedalPanel("Right pedal")
        pedals_row.addWidget(self.left_panel)
        pedals_row.addWidget(self.right_panel)
        root.addLayout(pedals_row)

        # --- seated / standing ---
        stance_frame = QFrame()
        stance_frame.setObjectName("card")
        stance_frame.setFrameShape(QFrame.Shape.StyledPanel)
        stance_layout = QVBoxLayout(stance_frame)
        toggle_row = QHBoxLayout()
        toggle_row.addStretch()
        self.seated_label = QLabel("Seated")
        self.standing_label = QLabel("Standing")
        for lbl in (self.seated_label, self.standing_label):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setContentsMargins(20, 8, 20, 8)
        toggle_row.addWidget(self.seated_label)
        toggle_row.addWidget(self.standing_label)
        toggle_row.addStretch()
        stance_layout.addLayout(toggle_row)
        self.stance_pct_label = QLabel("--% seated \u00b7 --% standing")
        self.stance_pct_label.setObjectName("mutedLabel")
        self.stance_pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stance_layout.addWidget(self.stance_pct_label)
        root.addWidget(stance_frame)
        self._set_stance_unavailable()

        # --- session timer + analyze/stop ---
        self.session_time_label = QLabel("00:00")
        self.session_time_label.setObjectName("sessionTimer")
        self.session_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.session_time_label)

        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.setFixedHeight(42)
        self.analyze_button.clicked.connect(self._toggle_session)
        self._style_analyze_button(active=False)
        root.addWidget(self.analyze_button)

        self.send_report_button = QPushButton("Send Report")
        self.send_report_button.setFixedHeight(36)
        self.send_report_button.clicked.connect(self._open_report_dialog)
        self.send_report_button.setVisible(False)  # samo nakon Stop-a
        root.addWidget(self.send_report_button)

    def _style_analyze_button(self, active: bool):
        if active:
            self.analyze_button.setText("Stop")
            self.analyze_button.setStyleSheet(
                "background-color: #3a1a1a; color: #e06060; border: 1px solid #7a2020; font-size: 15px; font-weight: 600; border-radius: 6px;"
            )
        else:
            self.analyze_button.setText("Analyze")
            self.analyze_button.setStyleSheet(
                "background-color: #185FA5; color: #e0e0e0; border: 1px solid #2a5a8c; font-size: 15px; font-weight: 600; border-radius: 6px;"
            )

    def _set_stance(self, standing: bool):
        active_style = "background-color: #1a3a5c; border: 1px solid #2a5a8c; color: #7ab3e0; font-weight: 600; border-radius: 6px;"
        inactive_style = "color: #666;"
        self.seated_label.setStyleSheet(inactive_style if standing else active_style)
        self.standing_label.setStyleSheet(active_style if standing else inactive_style)

    def _set_stance_unavailable(self):
        muted_style = "color: #555;"
        self.seated_label.setStyleSheet(muted_style)
        self.standing_label.setStyleSheet(muted_style)
        self.stance_pct_label.setText("Seated/standing unavailable - no dynamics from this source")

    # ---------------------------------------------------- data sources
    def _start_data_sources(self):
        self.using_real_power = False

        # ANT+ - jedan perzistentni Node za citav zivot appa (scan/HR/power
        # kanali se dinamicki dodaju/uklanjaju na njemu, USB uredjaj se ne
        # pusta i ponovno hvata izmedju scan i connect faze)
        self.ant_manager = AntManager()
        self.ant_manager.ready.connect(self._on_ant_ready)
        self.ant_manager.error.connect(self._on_ant_node_error)
        self.ant_manager.hr_connected.connect(lambda: self.hr_status.setText("HR: connected"))
        self.ant_manager.hr_updated.connect(self._on_hr_data)
        self.ant_manager.hr_error.connect(self._on_hr_error)

        self.ant_manager.power_connected.connect(self._on_power_connected)
        self.ant_manager.power_updated.connect(self._on_ant_power_data)
        self.ant_manager.power_error.connect(self._on_power_error)

        self.ant_manager.start()

    def _on_ant_ready(self):
        self.power_status.setEnabled(True)
        self.power_status.setText("Power: tap to pair")
        self.hr_status.setEnabled(True)
        self.hr_status.setText("HR: tap to pair")

    def _on_ant_node_error(self, message: str):
        self.power_status.setText("Power: ANT+ dongle not found")
        self.hr_status.setText("HR: ANT+ dongle not found")
        print(f"[ANT+] {message}")

    def _retry_hr(self):
        from ui.pairing_dialog import DevicePairingDialog

        dialog = DevicePairingDialog(
            "Pair heart rate monitor",
            self.ant_manager.start_hr_scan,
            self.ant_manager.stop_hr_scan,
            self.ant_manager.hr_scan_found,
            self.ant_manager.hr_error,
            self,
        )
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.selected_device_id is not None:
            self.hr_status.setText("HR: connecting...")
            self.ant_manager.connect_hr(dialog.selected_device_id)
        else:
            self.hr_status.setText("HR: not connected")

    def _on_hr_error(self, message: str):
        self.hr_status.setText("HR: error - tap to retry")
        print(f"[HR] {message}")

    def _retry_power(self):
        from ui.pairing_dialog import DevicePairingDialog

        dialog = DevicePairingDialog(
            "Pair power meter",
            self.ant_manager.start_power_scan,
            self.ant_manager.stop_power_scan,
            self.ant_manager.power_scan_found,
            self.ant_manager.power_error,
            self,
        )
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.selected_device_id is not None:
            self.power_status.setText("Power: connecting...")
            self.ant_manager.connect_power(dialog.selected_device_id)
        # ako je Cancel, ostajemo na simulatoru bez promjene statusa

    def _on_power_connected(self):
        self.using_real_power = True
        self.power_status.setText("Power: connected (basic - no dynamics)")

    def _on_power_error(self, message: str):
        self.power_status.setText("Power: error - tap to retry")
        print(f"[POWER] {message}")

    # ------------------------------------------------------ accumulators
    def _init_accumulators(self):
        self.avg_power = RunningAverage()
        self.avg_cadence = RunningAverage()
        self.avg_hr = RunningAverage()
        self.avg_balance_l = RunningAverage()
        self.avg_balance_r = RunningAverage()
        self.avg_left = _new_dynamics_accumulators()
        self.avg_right = _new_dynamics_accumulators()
        self.seated_samples = 0
        self.standing_samples = 0
        self.total_samples = 0

    def _reset_session(self):
        self._init_accumulators()
        self.session_seconds = 0
        self.session_time_label.setText("00:00")

    # ------------------------------------------------------- live data
    def _on_power_data(self, data: dict):
        if self.frozen:
            return

        power = data.get("power")
        cadence = data.get("cadence")
        if power is not None:
            self.power_value.setText(f"{power} W")
        if cadence is not None:
            self.cadence_value.setText(f"{cadence} rpm")

        balance_l = data.get("balance_l")
        balance_r = data.get("balance_r")
        if balance_l is not None and balance_r is not None:
            self.balance_value.setText(f"{balance_l}% / {balance_r}%")
            self.balance_bar.setValue(balance_l)
        else:
            self.balance_value.setText("--% / --%")

        if "left" in data and "right" in data:
            self.left_panel.update_data(data["left"])
            self.right_panel.update_data(data["right"])
            if self.session_active:
                self._accumulate_dynamics(self.avg_left, data["left"])
                self._accumulate_dynamics(self.avg_right, data["right"])
        else:
            self.left_panel.clear_data()
            self.right_panel.clear_data()

        stance_known = "standing" in data
        if stance_known:
            self._set_stance(data["standing"])
        else:
            self._set_stance_unavailable()

        if self.session_active:
            if power is not None:
                self.avg_power.add(power)
            if cadence is not None:
                self.avg_cadence.add(cadence)
            if balance_l is not None:
                self.avg_balance_l.add(balance_l)
                self.avg_balance_r.add(balance_r)
            if stance_known:
                self.total_samples += 1
                if data["standing"]:
                    self.standing_samples += 1
                else:
                    self.seated_samples += 1
            self._update_avg_labels()

    def _accumulate_dynamics(self, accumulators: dict, side_data: dict):
        for key in DYNAMICS_SCALAR_KEYS:
            value = side_data.get(key)
            if value is not None:
                accumulators[key].add(value)
        for key in DYNAMICS_RANGE_KEYS:
            value = side_data.get(key)
            if value is not None:
                start, end = value
                accumulators[f"{key}_start"].add(start)
                accumulators[f"{key}_end"].add(end)

    def _on_ant_power_data(self, data: dict):
        self._on_power_data(data)

    def _on_hr_data(self, value: int):
        if self.frozen:
            return
        self.hr_value.setText(f"{value} bpm")
        if self.session_active:
            self.avg_hr.add(value)

    def _update_avg_labels(self):
        bl = self.avg_balance_l.avg
        br = self.avg_balance_r.avg
        if bl is not None:
            self.balance_avg.setText(f"avg {bl:.0f}% / {br:.0f}%")
        if self.total_samples:
            seated_pct = self.seated_samples / self.total_samples * 100
            standing_pct = self.standing_samples / self.total_samples * 100
            self.stance_pct_label.setText(f"{seated_pct:.0f}% seated \u00b7 {standing_pct:.0f}% standing")

    # ------------------------------------------------------- session
    def _toggle_session(self):
        if not self.session_active and not self.frozen:
            # start
            self._reset_session()
            self.session_start_time = datetime.now()
            self.session_active = True
            self.session_timer.start(1000)
            self._style_analyze_button(active=True)
            self.send_report_button.setVisible(False)
        elif self.session_active:
            # stop -> freeze on summary
            self.session_active = False
            self.frozen = True
            self.session_timer.stop()
            self._freeze_on_summary()
            self._style_analyze_button(active=False)
            self.send_report_button.setVisible(True)
        else:
            # frozen -> start new session
            self.frozen = False
            self._reset_session()
            self.session_start_time = datetime.now()
            self.session_active = True
            self.session_timer.start(1000)
            self._style_analyze_button(active=True)
            self.send_report_button.setVisible(False)

    def _on_session_tick(self):
        self.session_seconds += 1
        mm, ss = divmod(self.session_seconds, 60)
        self.session_time_label.setText(f"{mm:02d}:{ss:02d}")

    def _freeze_on_summary(self):
        """Zamijeni live prikaz s izračunatim prosjecima sesije."""
        p = self.avg_power.avg
        c = self.avg_cadence.avg
        h = self.avg_hr.avg
        self.power_value.setText(f"{p:.0f} W" if p is not None else "--")
        self.cadence_value.setText(f"{c:.0f} rpm" if c is not None else "--")
        self.hr_value.setText(f"{h:.0f} bpm" if h is not None else "--")

        bl, br = self.avg_balance_l.avg, self.avg_balance_r.avg
        if bl is not None:
            self.balance_value.setText(f"{bl:.0f}% / {br:.0f}%")
            self.balance_bar.setValue(int(bl))
        self.balance_avg.setText("session average")

    def _open_report_dialog(self):
        from ui.report_dialog import ReportDialog

        summary = {
            "power": self.avg_power.avg,
            "cadence": self.avg_cadence.avg,
            "hr": self.avg_hr.avg,
            "balance_l": self.avg_balance_l.avg,
            "balance_r": self.avg_balance_r.avg,
            "left": {key: acc.avg for key, acc in self.avg_left.items()},
            "right": {key: acc.avg for key, acc in self.avg_right.items()},
        }
        if self.total_samples:
            summary["seated_pct"] = self.seated_samples / self.total_samples * 100
            summary["standing_pct"] = self.standing_samples / self.total_samples * 100

        start_str = self.session_start_time.strftime("%Y-%m-%d %H:%M") if self.session_start_time else "--"
        mm, ss = divmod(self.session_seconds, 60)
        duration_str = f"{mm:02d}:{ss:02d}"

        dialog = ReportDialog(start_str, duration_str, summary, self)
        dialog.exec()

    def closeEvent(self, event):
        if self.ant_manager is not None:
            self.ant_manager.shutdown()
        super().closeEvent(event)
