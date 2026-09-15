r"""
Auto-update preko GitHuba - verzionirani podfolderi, bez swap-helper procesa.

Zašto ovako: prijašnji pristup (folder-rename preko posebnog updater.exe) je
na Windowsu stalno nailazio na file-lock probleme - SysMain (Superfetch) i
Windows App-Compat shim engine drže kratkotrajnu read-only memory-mapped
sekciju na SVAKI svježe pokrenut/nepoznat .exe, čak i dugo nakon što se
proces ugasio, što blokira rename/delete operacije.

Novi pristup to potpuno zaobilazi: svaka verzija živi u svom VLASTITOM,
nikad-ponovno-dirnutom podfolderu (npr. "v0.21\"). Update samo:
1. Skine i raspakira novu verziju u NOV podfolder (npr. "v0.22\") - stari
   podfolderi se nikad ne prepisuju niti brišu, pa nema lock problema.
2. Prepiše current.txt (mali tekst fajl, nikad se ne "izvršava" pa ga
   AppCompat/SysMain ne dira) da pokazuje na novi podfolder.
3. Pokrene novi .exe direktno (subprocess.Popen) i ugasi se (os._exit(0)).

Desktop shortcut pokazuje na stabilan launcher.exe (zaseban, rijetko se
mijenja), koji čita current.txt i pokreće trenutno aktivnu verziju - vidi
launcher.py za taj dio.

FAMILY_ROOT struktura:

    Cycling Dynamics\              <- FAMILY_ROOT
    ├── launcher.exe
    ├── current.txt                <- npr. "v0.21"
    ├── v0.20\                     <- VERSION_DIR prošle verzije
    │   └── dynamics_app.exe
    └── v0.21\                     <- VERSION_DIR trenutne verzije (APP_ROOT
        └── dynamics_app.exe          kad ovaj kod trenutno radi)

Release zip (dist/dynamics_app_latest.zip) i dalje sadrži sadržaj Nuitka
.dist foldera direktno na top-levelu (dynamics_app.exe + ovisnosti) - isto
kao dosad, samo se sad raspakira u FAMILY_ROOT/<nova_verzija>/ umjesto u
sibling "_new" folder.
"""
import os
import sys
import shutil
import zipfile
import subprocess
import tempfile
import time

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from version import VERSION

GITHUB_USER = "elpaho"
GITHUB_REPO = "cycling-dynamics-app"
GITHUB_BRANCH = "master"

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
VERSION_URL = f"{RAW_BASE}/version.py"
ZIP_URL = f"{RAW_BASE}/dist/dynamics_app_latest.zip"


def _no_cache_url(url: str) -> str:
    """raw.githubusercontent.com zna cache-irati par minuta preko CDN-a -
    timestamp query param tjera svjez fetch svaki put."""
    return f"{url}?_={int(time.time())}"

# VERSION_DIR = folder u kojem trenutno živi POKRENUTI dynamics_app.exe
# (npr. ...\Cycling Dynamics\v0.21). FAMILY_ROOT je jedan nivo iznad - tu
# žive svi verzionirani podfolderi, current.txt i launcher.exe.
VERSION_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
FAMILY_ROOT = os.path.dirname(VERSION_DIR)
POINTER_FILE = os.path.join(FAMILY_ROOT, "current.txt")
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

    progress = pyqtSignal(int)             # -1 = indeterminate, 0-100 = %
    download_done = pyqtSignal(bool, str)  # success, remote_version ili error poruka

    def check_for_update(self):
        try:
            resp = requests.get(_no_cache_url(VERSION_URL), timeout=8)
            resp.raise_for_status()
            remote_version = _parse_remote_version(resp.text)
            if remote_version and _version_tuple(remote_version) > _version_tuple(VERSION):
                self.update_available.emit(remote_version)
            else:
                self.no_update.emit()
        except Exception as e:
            self.check_failed.emit(str(e))

    def download_and_install(self, remote_version: str):
        """Skida zip i raspakira ga u FAMILY_ROOT/<remote_version>/ - NOV, nikad prije koristen folder."""
        try:
            target_dir = os.path.join(FAMILY_ROOT, remote_version)
            if os.path.exists(target_dir):
                # već postoji (npr. ostatak prekinutog pokušaja) - očisti
                shutil.rmtree(target_dir, ignore_errors=True)
            os.makedirs(target_dir, exist_ok=True)

            with requests.get(_no_cache_url(ZIP_URL), stream=True, timeout=30) as resp:
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
                zf.extractall(target_dir)

            os.remove(tmp_path)
            self.download_done.emit(True, remote_version)
        except Exception as e:
            self.download_done.emit(False, str(e))


class UpdateWorker(QThread):
    """Pokreće provjeru/download u pozadinskom threadu."""
    def __init__(self, checker: UpdateChecker, mode: str, remote_version: str = None):
        super().__init__()
        self.checker = checker
        self.mode = mode  # "check" ili "download"
        self.remote_version = remote_version

    def run(self):
        if self.mode == "check":
            self.checker.check_for_update()
        elif self.mode == "download":
            self.checker.download_and_install(self.remote_version)


def apply_update_and_restart(remote_version: str):
    """
    Zove se NAKON uspješnog download_and_install() - FAMILY_ROOT/<remote_version>/
    već postoji i popunjen je. Prepiše current.txt (atomično preko os.replace),
    pokrene novi exe direktno (bez ikakvog swap-helpera), i ugasi ovaj proces.

    Nema file-lock rizika: current.txt je mali tekst fajl koji se ne izvršava
    (App-Compat/SysMain ga ne diraju), a stari VERSION_DIR se uopće ne dira.
    """
    new_exe = os.path.join(FAMILY_ROOT, remote_version, APP_EXE_NAME)
    if not os.path.isfile(new_exe):
        raise FileNotFoundError(f"Novi exe nije pronađen na {new_exe}")

    tmp_pointer = POINTER_FILE + ".tmp"
    with open(tmp_pointer, "w", encoding="utf-8") as f:
        f.write(remote_version)
    os.replace(tmp_pointer, POINTER_FILE)  # atomično na istom volumenu

    time.sleep(0.3)  # da se Qt prozori stignu zatvoriti prije nego novi krene
    subprocess.Popen([new_exe], cwd=os.path.dirname(new_exe))
    os._exit(0)