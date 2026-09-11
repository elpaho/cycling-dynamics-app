from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QProgressBar, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer

from simulator.power_simulator import PowerSimulator
from ant.hr_receiver import HeartRateReceiver


def _box(title: str) -> tuple[QFrame, QLabel, QLabel]:
    """Kreira jednu 'metric' kućicu (naslov + veliki broj)."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)

    title_label = QLabel(title)
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title_label.setStyleSheet("color: #888; font-size: 12px;")

    value_label = QLabel("--")
    value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    value_label.setStyleSheet("font-size: 26px; font-weight: 600;")

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
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(title_label)

        grid = QGridLayout()
        self.value_labels = {}
        for row, (label_text, key, _unit) in enumerate(self.ROWS):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #888; font-size: 12px;")
            val = QLabel("--")
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            val.setStyleSheet("font-size: 13px;")
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cycling Dynamics")
        self.resize(560, 720)

        self.session_active = False
        self.frozen = False
        self.session_seconds = 0

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
        self.power_status = QPushButton("Power: Simulator (dev)")
        self.power_status.setEnabled(False)
        self.hr_status = QPushButton("HR: tap to pair")
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
        balance_frame.setFrameShape(QFrame.Shape.StyledPanel)
        balance_layout = QVBoxLayout(balance_frame)
        header = QHBoxLayout()
        left_hdr = QLabel("Power balance")
        left_hdr.setStyleSheet("color: #888; font-size: 12px;")
        self.balance_value = QLabel("--% / --%")
        self.balance_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.balance_value.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.balance_avg = QLabel("avg --% / --%")
        self.balance_avg.setStyleSheet("color: #888; font-size: 12px;")
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
        self.stance_pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stance_pct_label.setStyleSheet("color: #888; font-size: 12px;")
        stance_layout.addWidget(self.stance_pct_label)
        root.addWidget(stance_frame)
        self._set_stance(False)

        # --- session timer + analyze/stop ---
        self.session_time_label = QLabel("00:00")
        self.session_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.session_time_label.setStyleSheet("font-size: 13px; color: #888;")
        root.addWidget(self.session_time_label)

        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.setFixedHeight(42)
        self.analyze_button.clicked.connect(self._toggle_session)
        self._style_analyze_button(active=False)
        root.addWidget(self.analyze_button)

    def _style_analyze_button(self, active: bool):
        if active:
            self.analyze_button.setText("Stop")
            self.analyze_button.setStyleSheet(
                "background-color: #c0392b; color: white; font-size: 15px; font-weight: 600;"
            )
        else:
            self.analyze_button.setText("Analyze")
            self.analyze_button.setStyleSheet(
                "background-color: #378ADD; color: white; font-size: 15px; font-weight: 600;"
            )

    def _set_stance(self, standing: bool):
        active_style = "background-color: rgba(55,138,221,0.15); border: 1px solid #378ADD; color: #185FA5; font-weight: 600; border-radius: 6px;"
        inactive_style = "color: #888;"
        self.seated_label.setStyleSheet(inactive_style if standing else active_style)
        self.standing_label.setStyleSheet(active_style if standing else inactive_style)

    # ---------------------------------------------------- data sources
    def _start_data_sources(self):
        # Simulator - MAKNUTI kad ANT+ Bike Power / cycling dynamics sloj bude gotov
        self.power_sim = PowerSimulator(interval_ms=250)
        self.power_sim.data_updated.connect(self._on_power_data)

        # ANT+ HR - stvarni hardver
        self.hr_receiver = None
        self.hr_device_id = 0  # 0 = wildcard (prvi koji se javi), mijenja se nakon pairinga

    def _start_hr(self, device_id: int = None):
        if device_id is not None:
            self.hr_device_id = device_id
        self.hr_status.setText("HR: connecting...")
        self.hr_receiver = HeartRateReceiver(device_id=self.hr_device_id)
        self.hr_receiver.device_found.connect(lambda: self.hr_status.setText("HR: connected"))
        self.hr_receiver.error.connect(self._on_hr_error)
        self.hr_receiver.hr_updated.connect(self._on_hr_data)
        self.hr_receiver.start()

    def _retry_hr(self):
        from ui.pairing_dialog import HRPairingDialog

        if self.hr_receiver is not None and self.hr_receiver.isRunning():
            self.hr_receiver.stop()

        dialog = HRPairingDialog(self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.selected_device_id is not None:
            self._start_hr(device_id=dialog.selected_device_id)
        else:
            self.hr_status.setText("HR: not connected")

    def _on_hr_error(self, message: str):
        self.hr_status.setText("HR: error - tap to retry")
        print(f"[HR] {message}")

    # ------------------------------------------------------ accumulators
    def _init_accumulators(self):
        self.avg_power = RunningAverage()
        self.avg_cadence = RunningAverage()
        self.avg_hr = RunningAverage()
        self.avg_balance_l = RunningAverage()
        self.avg_balance_r = RunningAverage()
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

        self.power_value.setText(f"{data['power']} W")
        self.cadence_value.setText(f"{data['cadence']} rpm")
        self.balance_value.setText(f"{data['balance_l']}% / {data['balance_r']}%")
        self.balance_bar.setValue(data["balance_l"])
        self.left_panel.update_data(data["left"])
        self.right_panel.update_data(data["right"])
        self._set_stance(data["standing"])

        if self.session_active:
            self.avg_power.add(data["power"])
            self.avg_cadence.add(data["cadence"])
            self.avg_balance_l.add(data["balance_l"])
            self.avg_balance_r.add(data["balance_r"])
            self.total_samples += 1
            if data["standing"]:
                self.standing_samples += 1
            else:
                self.seated_samples += 1
            self._update_avg_labels()

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
            self.session_active = True
            self.session_timer.start(1000)
            self._style_analyze_button(active=True)
        elif self.session_active:
            # stop -> freeze on summary
            self.session_active = False
            self.frozen = True
            self.session_timer.stop()
            self._freeze_on_summary()
            self._style_analyze_button(active=False)
        else:
            # frozen -> start new session
            self.frozen = False
            self._reset_session()
            self.session_active = True
            self.session_timer.start(1000)
            self._style_analyze_button(active=True)

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

    def closeEvent(self, event):
        self.power_sim.stop()
        if self.hr_receiver is not None:
            self.hr_receiver.stop()
        super().closeEvent(event)
