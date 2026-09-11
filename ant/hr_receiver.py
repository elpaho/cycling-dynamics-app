"""
ANT+ Heart Rate receiver preko openant biblioteke.

NAPOMENA: openant.Node().start() je blocking poziv (interni event loop),
zato mora raditi u zasebnom QThreadu. Point provjeriti tačan API nakon prve
instalacije openant-a (verzije se znaju razlikovati) - ovo je napisano prema
standardnom openant primjeru za HeartRate device profile.
"""
from PyQt6.QtCore import QThread, pyqtSignal


def _force_bundled_libusb_backend():
    """
    pyusb inace trazi libusb-1.0.dll preko ctypes.util.find_library(), sto na
    Windowsu cesto ne uspije naci DLL cak i kad je Zadig driver ispravno
    postavljen (vidjeno u praksi - libusb1 backend vraca None dok libusb0
    vidi 0 uredjaja jer je vezan za drugi tip drivera).

    libusb-package nosi kompajliranu libusb-1.0 biblioteku unutar samog
    Python paketa (instalira se preko requirements.txt na SVAKOM racunalu,
    ne treba rucno kopiranje u System32). Ovdje presrecemo pyusb-ov
    get_backend() da uvijek koristi tu bundlanu putanju.
    """
    try:
        import libusb_package
        import usb.backend.libusb1 as libusb1

        lib_path = libusb_package.get_library_path()
        if not lib_path:
            return  # paket nije uspio ugraditi binarku za ovu platformu/arh.

        _original_get_backend = libusb1.get_backend

        def _patched_get_backend(find_library=None, **kwargs):
            return _original_get_backend(find_library=lambda x: lib_path, **kwargs)

        libusb1.get_backend = _patched_get_backend
    except ImportError:
        pass  # libusb-package nije instaliran - pyusb ce probati default potragu


_force_bundled_libusb_backend()


class HeartRateReceiver(QThread):
    hr_updated = pyqtSignal(int)
    device_found = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, device_id: int = 0, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self._node = None
        self._device = None
        self._running = False

    def run(self):
        try:
            from openant.easy.node import Node
            from openant.devices import ANTPLUS_NETWORK_KEY
            from openant.devices.heart_rate import HeartRate, HeartRateData
        except ImportError as e:
            self.error.emit(f"openant nije instaliran: {e}")
            return

        try:
            self._node = Node()
            self._node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)
            self._device = HeartRate(self._node, device_id=self.device_id)

            def on_found():
                self.device_found.emit()

            def on_device_data(page: int, page_name: str, data):
                if isinstance(data, HeartRateData) and data.heart_rate:
                    self.hr_updated.emit(int(data.heart_rate))

            self._device.on_found = on_found
            self._device.on_device_data = on_device_data

            self._running = True
            self._node.start()  # blocking dok se ne pozove node.stop()
        except Exception as e:
            detail = str(e).strip()
            message = f"{type(e).__name__}: {detail}" if detail else type(e).__name__
            self.error.emit(message)
        finally:
            self._cleanup()

    def _cleanup(self):
        try:
            if self._device:
                self._device.close_channel()
        except Exception:
            pass
        try:
            if self._node:
                self._node.stop()
        except Exception:
            pass

    def stop(self):
        self._running = False
        try:
            if self._node:
                self._node.stop()
        except Exception:
            pass
        self.wait(2000)
