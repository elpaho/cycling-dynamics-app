"""
Simulator power/cadence/cycling-dynamics podataka.
Privremena zamjena za stvarne Rally pedale - MAKNUTI kad ANT+ Bike Power
sloj bude implementiran.

Emitira isti "shape" podataka kakav bi stigao sa stvarnog dual-sided
power meter-a preko ANT+ Cycling Dynamics extension page-ova, na frekvenciji
~4 Hz (kao stvarni ANT+ broadcast).
"""
import random

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class PowerSimulator(QObject):
    data_updated = pyqtSignal(dict)

    def __init__(self, interval_ms: int = 250, parent=None):
        super().__init__(parent)
        self._power = 220.0
        self._cadence = 85.0
        self._balance_l = 50.0
        self._standing = False
        self._stand_timer = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(interval_ms)

    def _walk(self, value, step, lo, hi):
        value += random.uniform(-step, step)
        return max(lo, min(hi, value))

    def _tick(self):
        self._power = self._walk(self._power, 8, 120, 320)
        self._cadence = self._walk(self._cadence, 2, 60, 100)
        self._balance_l = self._walk(self._balance_l, 1.5, 42, 58)

        # povremeno "ustani" na 10-20 sekundi
        self._stand_timer += 1
        if self._stand_timer > random.randint(40, 80):
            self._standing = not self._standing
            self._stand_timer = 0

        balance_r = 100.0 - self._balance_l

        data = {
            "power": round(self._power),
            "cadence": round(self._cadence),
            "balance_l": round(self._balance_l),
            "balance_r": round(balance_r),
            "standing": self._standing,
            "left": {
                "torque_eff": round(self._walk(75, 3, 55, 90)),
                "pedal_smooth": round(self._walk(60, 3, 40, 80)),
                "pco_mm": round(self._walk(3, 2, -8, 8)),
                "power_phase": (round(self._walk(15, 3, 0, 30)), round(self._walk(170, 3, 150, 190))),
                "peak_phase": (round(self._walk(62, 3, 45, 80)), round(self._walk(104, 3, 90, 120))),
            },
            "right": {
                "torque_eff": round(self._walk(78, 3, 55, 90)),
                "pedal_smooth": round(self._walk(63, 3, 40, 80)),
                "pco_mm": round(self._walk(-2, 2, -8, 8)),
                "power_phase": (round(self._walk(12, 3, 0, 30)), round(self._walk(168, 3, 150, 190))),
                "peak_phase": (round(self._walk(58, 3, 45, 80)), round(self._walk(101, 3, 90, 120))),
            },
        }
        self.data_updated.emit(data)

    def stop(self):
        self._timer.stop()
