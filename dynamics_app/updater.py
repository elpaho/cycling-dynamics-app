"""
Auto-update preko GitHuba.
Isti pattern kao tacx-trainer-app: version.py + dist/<app>_latest.zip na GitHubu,
provjera preko raw.githubusercontent.com, download + raspakiravanje preko trenutne
instalacije, restart preko subprocess.Popen + os._exit(0) (Windows-safe).
"""
import os
import sys
import time
import zipfile
import subprocess
import tempfile

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from version import VERSION

GITHUB_USER = "elpaho"
GITHUB_REPO = "cycling-dynamics-app"
GITHUB_BRANCH = "master"

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
VERSION_URL = f"{RAW_BASE}/version.py"
ZIP_URL = f"{RAW_BASE}/dist/dynamics_app_latest.zip"

APP_ROOT = os.path.dirname(os.path.abspath(sys.argv[0]))


def _parse_remote_version(text: str) -> str:
    # očekuje liniju: VERSION = "vX.X"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("VERSION"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class UpdateChecker(QObject):
    """Qt objekt koji emitira signale iz background threadova (thread-safe UI update)."""
    update_available = pyqtSignal(str)   # remote version string
    no_update = pyqtSignal()
    check_failed = pyqtSignal(str)

    progress = pyqtSignal(int)           # -1 = indeterminate, 0-100 = %
    download_done = pyqtSignal(bool, str)  # success, message

    def check_for_update(self):
        try:
            resp = requests.get(VERSION_URL, timeout=8)
            resp.raise_for_status()
            remote_version = _parse_remote_version(resp.text)
            if remote_version and remote_version != VERSION:
                self.update_available.emit(remote_version)
            else:
                self.no_update.emit()
        except Exception as e:
            self.check_failed.emit(str(e))

    def download_and_install(self):
        try:
            with requests.get(ZIP_URL, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0

                tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
                with os.fdopen(tmp_fd, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(int(downloaded * 100 / total))
                        else:
                            self.progress.emit(-1)

            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(APP_ROOT)

            os.remove(tmp_path)
            self.download_done.emit(True, "Update installed.")
        except Exception as e:
            self.download_done.emit(False, str(e))


class UpdateWorker(QThread):
    """Pokreće provjeru/download u pozadinskom threadu."""
    def __init__(self, checker: UpdateChecker, mode: str):
        super().__init__()
        self.checker = checker
        self.mode = mode  # "check" ili "download"

    def run(self):
        if self.mode == "check":
            self.checker.check_for_update()
        elif self.mode == "download":
            self.checker.download_and_install()


def restart_app():
    """Restartaj aplikaciju - Windows kompatibilno (subprocess.Popen + os._exit)."""
    python = sys.executable
    script = os.path.abspath(sys.argv[0])
    time.sleep(0.5)  # da se Qt prozori stignu zatvoriti
    subprocess.Popen(
        [python, script],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    os._exit(0)
