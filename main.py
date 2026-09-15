# nuitka-project: --standalone
# nuitka-project: --enable-plugin=pyqt6
# nuitka-project: --output-filename=dynamics_app.exe
# nuitka-project: --include-data-files=cacert.pem=cacert.pem
# nuitka-project: --include-package-data=libusb_package
# nuitka-project: --windows-console-mode=force
# ^ force = konzola VIDLJIVA za sad (radi print/error outputa dok testiramo).
#   Kad sve bude stabilno, promijeni na --windows-console-mode=disable i rebuildaj.
#
# NAPOMENA o cacert.pem: Nuitkin --include-package-data=certifi ima poznat bug
# (WARNING: Duplicate data file... pa ga ignorira umjesto ukljuci). Zato
# nosimo VLASTITU kopiju certifi cacert.pem fajla (obican data file, ne
# "package data") i eksplicitno je registriramo kod requests-a ispod, prije
# bilo kakvog mreznog poziva.

import os
import sys

if getattr(sys, "frozen", False) or "__compiled__" in dir():
    _bundled_cacert = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "cacert.pem")
    if os.path.isfile(_bundled_cacert):
        os.environ["SSL_CERT_FILE"] = _bundled_cacert
        os.environ["REQUESTS_CA_BUNDLE"] = _bundled_cacert

from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PyQt6.QtCore import Qt, QTimer

from version import VERSION
from updater import UpdateChecker, UpdateWorker, apply_update_and_restart
from ui.main_window import MainWindow, DARK_STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    window = MainWindow()
    window.setWindowTitle(f"Cycling Dynamics {VERSION}")

    checker = UpdateChecker()

    def on_update_available(remote_version: str):
        print(f"[update] version {remote_version} available, downloading automatically...")
        _download_update(app, window, checker, remote_version)

    def on_no_update():
        print(f"[update] Already on latest version ({VERSION}).")

    def on_check_failed(message: str):
        print(f"[update] check failed: {message}")

    checker.update_available.connect(on_update_available)
    checker.no_update.connect(on_no_update)
    checker.check_failed.connect(on_check_failed)

    check_worker = UpdateWorker(checker, mode="check")
    print("[update] Checking for updates...")
    check_worker.start()
    # čuvamo referencu da je garbage collector ne pokupi prerano
    window._check_worker = check_worker

    window.show()
    sys.exit(app.exec())


def _download_update(app, window, checker: UpdateChecker, remote_version: str):
    progress = QProgressDialog("Downloading update...", None, 0, 100, window)
    progress.setWindowTitle("Update")
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.show()

    def on_progress(pct: int):
        if pct < 0:
            progress.setMaximum(0)  # indeterminate
        else:
            if progress.maximum() == 0:
                progress.setMaximum(100)
            progress.setValue(pct)

    def on_done(success: bool, message: str):
        progress.close()
        if success:
            QMessageBox.information(window, "Update", "Update downloaded. The app will restart.")
            try:
                apply_update_and_restart(remote_version)
            except FileNotFoundError as e:
                QMessageBox.critical(window, "Update failed", str(e))
        else:
            QMessageBox.warning(window, "Update failed", f"Could not install update:\n{message}")

    checker.progress.connect(on_progress)
    checker.download_done.connect(on_done)

    download_worker = UpdateWorker(checker, mode="download", remote_version=remote_version)
    download_worker.start()
    window._download_worker = download_worker


if __name__ == "__main__":
    main()