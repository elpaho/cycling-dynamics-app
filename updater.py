"""
Auto-update preko GitHuba, prilagođeno za Nuitka standalone distribuciju.

Zašto ne raspakiravamo preko sebe kao ranije: kompajlirani .exe (i svaki
DLL/pyd koji je učitao) je Windows-lockan dok proces radi, pa se ne može
prepisati "u hodu", niti se app može sam restartati python-relaunch
trikom (nema više python.exe, samo standalone exe).

Novi flow:
1. Skini zip i raspakiraj ga u SIBLING folder (APP_ROOT + "_new") - ovo je
   siguran korak, ne dira fajlove koje trenutni proces koristi.
2. Pozovi odvojeni updater.exe (folder-swap helper, kompajliran zasebno
   Nuitkom, živi u APP_ROOT/updater/updater.exe) s --old-dir/--new-dir/
   --exe-name, pa se odmah ugasi preko os._exit(0).
3. updater.exe pričeka da se lock oslobodi, zamijeni folder, pokrene novi
   .exe, ugasi se sam.

VAŽNO: ovo pretpostavlja da je app pokrenut kao Nuitka standalone build s
prisutnim APP_ROOT/updater/updater.exe. Pokretanje kao običan `python
main.py` (dev mode bez tog foldera) će 'apply_update_and_restart' pucanjem
ako updater.exe ne postoji - to je namjerno, da se odmah primijeti fali li
nešto u distribuciji, a ne tiho ušuti grešku.

Release zip (dist/dynamics_app_latest.zip) od sad treba sadržavati SADRŽAJ
Nuitka .dist foldera direktno na top-levelu (exe + _internal/... itd), NE
umotano u dodatni "dynamics_app/" folder - jer se sad extracta u čist
sibling folder, ne preko postojeće instalacije.
"""
import os
import sys
import shutil
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
NEW_DIR = APP_ROOT + "_new"

UPDATER_SUBDIR = "updater"
UPDATER_EXE_NAME = "updater.exe"
APP_EXE_NAME = "dynamics_app.exe"


def _version_tuple(v: str) -> tuple:
    """'v1.2' -> (1, 2); robustno na fali/extra dijelove."""
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


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
            if remote_version and _version_tuple(remote_version) > _version_tuple(VERSION):
                self.update_available.emit(remote_version)
            else:
                self.no_update.emit()
        except Exception as e:
            self.check_failed.emit(str(e))

    def download_and_install(self):
        """Skida zip i raspakirava ga u NEW_DIR (sibling folder) - NE preko APP_ROOT."""
        print(f"[update] APP_ROOT={APP_ROOT}")
        print(f"[update] NEW_DIR={NEW_DIR}")
        try:
            if os.path.exists(NEW_DIR):
                shutil.rmtree(NEW_DIR, ignore_errors=True)
            os.makedirs(NEW_DIR, exist_ok=True)

            old_backup = APP_ROOT + "_old"
            if os.path.exists(old_backup):
                shutil.rmtree(old_backup, ignore_errors=True)

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
                self._extract_with_retry(zf, NEW_DIR)

            os.remove(tmp_path)
            self.download_done.emit(True, "Update downloaded.")
        except Exception as e:
            self.download_done.emit(False, str(e))

    @staticmethod
    def _extract_with_retry(zf: zipfile.ZipFile, target_dir: str, retries: int = 15, delay: float = 1.5):
        """
        extractall() zna pući s PermissionError ako Windows Defender (ili
        neki drugi AV) nakratko zaključa svježe napisanu DLL/exe datoteku dok
        je skenira - obično prođe unutar par sekundi. Retry cijelog
        extractall-a je jednostavnije i sigurnije nego pokušavati preskočiti
        pojedinačne fajlove.
        """
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                zf.extractall(target_dir)
                return
            except PermissionError as e:
                last_error = e
                time.sleep(delay)
        raise last_error


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


def apply_update_and_restart():
    """
    Zove se NAKON uspješnog download_and_install() (NEW_DIR već postoji i
    popunjen je). Pokreće odvojeni updater.exe koji čeka da se ovaj proces
    ugasi, zamijeni APP_ROOT sadržajem iz NEW_DIR, i pokrene novi .exe.

    Odmah nakon pokretanja updatera gasimo se preko os._exit(0) - ne radimo
    nikakav cleanup nakon ovoga, updater.exe pretpostavlja da ćemo umrijeti
    za par trenutaka.
    """
    updater_exe = os.path.join(APP_ROOT, UPDATER_SUBDIR, UPDATER_EXE_NAME)
    if not os.path.isfile(updater_exe):
        raise FileNotFoundError(
            f"updater.exe nije pronađen na {updater_exe} - provjeri da je "
            f"'{UPDATER_SUBDIR}/' folder dio distribucije (Nuitka standalone build)."
        )
    subprocess.Popen([
        updater_exe,
        "--old-dir", APP_ROOT,
        "--new-dir", NEW_DIR,
        "--exe-name", APP_EXE_NAME,
        "--wait-retries", "60",
        "--wait-delay", "1",
    ])
    os._exit(0)