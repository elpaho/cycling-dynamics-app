import sys

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
        _download_update(app, window, checker)

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


def _download_update(app, window, checker: UpdateChecker):
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
                apply_update_and_restart()
            except FileNotFoundError as e:
                QMessageBox.critical(window, "Update failed", str(e))
        else:
            QMessageBox.warning(window, "Update failed", f"Could not install update:\n{message}")

    checker.progress.connect(on_progress)
    checker.download_done.connect(on_done)

    download_worker = UpdateWorker(checker, mode="download")
    download_worker.start()
    window._download_worker = download_worker


if __name__ == "__main__":
    main()