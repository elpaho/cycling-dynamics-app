import sys

from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PyQt6.QtCore import Qt, QTimer

from version import VERSION
from updater import UpdateChecker, UpdateWorker, restart_app
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.setWindowTitle(f"Cycling Dynamics {VERSION}")

    checker = UpdateChecker()

    def on_update_available(remote_version: str):
        reply = QMessageBox.question(
            window,
            "Update available",
            f"New version {remote_version} is available (current: {VERSION}).\nUpdate now?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            _download_update(app, window, checker)

    def on_no_update():
        pass  # tiho, nema dijaloga ako je sve up to date

    def on_check_failed(message: str):
        print(f"[update] check failed: {message}")

    checker.update_available.connect(on_update_available)
    checker.no_update.connect(on_no_update)
    checker.check_failed.connect(on_check_failed)

    check_worker = UpdateWorker(checker, mode="check")
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
            QMessageBox.information(window, "Update", "Update installed. The app will restart.")
            restart_app()
        else:
            QMessageBox.warning(window, "Update failed", f"Could not install update:\n{message}")

    checker.progress.connect(on_progress)
    checker.download_done.connect(on_done)

    download_worker = UpdateWorker(checker, mode="download")
    download_worker.start()
    window._download_worker = download_worker


if __name__ == "__main__":
    main()
