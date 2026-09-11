"""
Jedan perzistentni ANT+ Node koji živi cijeli životni vijek aplikacije.

Zašto ovako: raniji pristup (zaseban Node za scan, pa ga ugasi, pa novi Node
za stvarno spajanje) je na Windowsu davao "Access Denied" jer USB handle nije
pouzdano bio oslobođen između gašenja jednog i otvaranja drugog Node-a, bez
obzira na pauze. Kanali (scan, HR, kasnije i Bike Power/dynamics) se sad
dinamički dodaju/uklanjaju na ISTOM već otvorenom Node-u, pa se USB uređaj
nikad ne pušta i ponovno hvata.
"""
from PyQt6.QtCore import QThread, pyqtSignal


def _force_bundled_libusb_backend():
    """
    pyusb inace trazi libusb-1.0.dll preko ctypes.util.find_library(), sto na
    Windowsu cesto ne uspije naci DLL cak i kad je Zadig driver ispravno
    postavljen. libusb-package nosi kompajliranu libusb-1.0 biblioteku unutar
    samog Python paketa - ovdje presrecemo pyusb-ov get_backend() da uvijek
    koristi tu bundlanu putanju.
    """
    try:
        import libusb_package
        import usb.backend.libusb1 as libusb1

        lib_path = libusb_package.get_library_path()
        if not lib_path:
            return

        _original_get_backend = libusb1.get_backend

        def _patched_get_backend(find_library=None, **kwargs):
            return _original_get_backend(find_library=lambda x: lib_path, **kwargs)

        libusb1.get_backend = _patched_get_backend
    except ImportError:
        pass


_force_bundled_libusb_backend()


class AntManager(QThread):
    ready = pyqtSignal()
    error = pyqtSignal(str)

    hr_scan_found = pyqtSignal(int)
    hr_connected = pyqtSignal()
    hr_updated = pyqtSignal(int)
    hr_error = pyqtSignal(str)

    power_scan_found = pyqtSignal(int)
    power_connected = pyqtSignal()
    power_updated = pyqtSignal(dict)
    power_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._node = None
        self._scanner = None
        self._hr_device = None
        self._power_scanner = None
        self._power_device = None

    # ------------------------------------------------------------- thread
    def run(self):
        try:
            from openant.easy.node import Node
            from openant.devices import ANTPLUS_NETWORK_KEY
        except ImportError as e:
            self.error.emit(f"openant nije instaliran: {e}")
            return

        try:
            self._node = Node()
            self._node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)
            self.ready.emit()
            self._node.start()  # blocking - zivi dok se ne pozove shutdown()
        except Exception as e:
            self.error.emit(self._format_error(e))

    @staticmethod
    def _format_error(e: Exception) -> str:
        detail = str(e).strip()
        return f"{type(e).__name__}: {detail}" if detail else type(e).__name__

    # ------------------------------------------------------------- HR scan
    def start_hr_scan(self):
        if not self._node:
            self.hr_error.emit("ANT+ node not ready yet")
            return
        try:
            from openant.devices.scanner import Scanner
            from openant.devices.common import DeviceType

            seen = set()
            self._scanner = Scanner(self._node, device_type=DeviceType.HeartRate.value)

            def on_found(device_tuple):
                device_id, _device_type, _trans_type = device_tuple
                if device_id not in seen:
                    seen.add(device_id)
                    self.hr_scan_found.emit(device_id)

            self._scanner.on_found = on_found
        except Exception as e:
            self.hr_error.emit(self._format_error(e))

    def stop_hr_scan(self):
        if self._scanner is not None:
            try:
                self._scanner.close_channel()
            except Exception:
                pass
            self._scanner = None

    # ------------------------------------------------------------- HR connect
    def connect_hr(self, device_id: int):
        self.stop_hr_scan()
        if self._hr_device is not None:
            try:
                self._hr_device.close_channel()
            except Exception:
                pass
            self._hr_device = None

        try:
            from openant.devices.heart_rate import HeartRate, HeartRateData

            self._hr_device = HeartRate(self._node, device_id=device_id)

            def on_found():
                self.hr_connected.emit()

            def on_data(page: int, page_name: str, data):
                if isinstance(data, HeartRateData) and data.heart_rate:
                    self.hr_updated.emit(int(data.heart_rate))

            self._hr_device.on_found = on_found
            self._hr_device.on_device_data = on_data
        except Exception as e:
            self.hr_error.emit(self._format_error(e))

    # ------------------------------------------------------------- power scan
    def start_power_scan(self):
        if not self._node:
            self.power_error.emit("ANT+ node not ready yet")
            return
        try:
            from openant.devices.scanner import Scanner
            from openant.devices.common import DeviceType

            seen = set()
            self._power_scanner = Scanner(self._node, device_type=DeviceType.PowerMeter.value)

            def on_found(device_tuple):
                device_id, _device_type, _trans_type = device_tuple
                if device_id not in seen:
                    seen.add(device_id)
                    self.power_scan_found.emit(device_id)

            self._power_scanner.on_found = on_found
        except Exception as e:
            self.power_error.emit(self._format_error(e))

    def stop_power_scan(self):
        if self._power_scanner is not None:
            try:
                self._power_scanner.close_channel()
            except Exception:
                pass
            self._power_scanner = None

    # ------------------------------------------------------------- power connect
    def connect_power(self, device_id: int):
        """
        Spaja se na standardni ANT+ Power Meter profil - Neo 2T i single-side
        pedale salju samo instantaneous_power/cadence (i grubu L/R procjenu
        preko pedal-power postotka na standard power pageu). Cycling Dynamics
        (PCO, torque eff., pedal smoothness, power/peak phase) NIJE dio ovog
        standardnog profila - to dolazi tek s pravim dual-side Rally pedalama
        preko posebnih extension pagea koje jos treba parsirati rucno.
        """
        self.stop_power_scan()
        if self._power_device is not None:
            try:
                self._power_device.close_channel()
            except Exception:
                pass
            self._power_device = None

        try:
            from openant.devices.power_meter import PowerMeter, PowerData

            self._power_device = PowerMeter(self._node, device_id=device_id)

            def on_found():
                self.power_connected.emit()

            def on_data(page: int, page_name: str, data):
                if isinstance(data, PowerData):
                    payload = {
                        "power": data.instantaneous_power,
                        "cadence": data.cadence if data.cadence != 255 else None,
                    }
                    if data.left_power >= 0 and data.right_power >= 0:
                        total = data.left_power + data.right_power
                        if total > 0:
                            payload["balance_l"] = round(data.left_power / total * 100)
                            payload["balance_r"] = round(data.right_power / total * 100)
                    self.power_updated.emit(payload)

            self._power_device.on_found = on_found
            self._power_device.on_device_data = on_data
        except Exception as e:
            self.power_error.emit(self._format_error(e))

    # ------------------------------------------------------------- shutdown
    def shutdown(self):
        """Zatvori sve kanale (redoslijed bitan - prije nego node/driver umre), pa ugasi node."""
        try:
            if self._scanner is not None:
                self._scanner.close_channel()
        except Exception:
            pass
        try:
            if self._hr_device is not None:
                self._hr_device.close_channel()
        except Exception:
            pass
        try:
            if self._power_scanner is not None:
                self._power_scanner.close_channel()
        except Exception:
            pass
        try:
            if self._power_device is not None:
                self._power_device.close_channel()
        except Exception:
            pass
        try:
            if self._node is not None:
                self._node.stop()
        except Exception:
            pass
        self.wait(2000)
