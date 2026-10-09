# PyInstaller: собирает Muninhall для Windows в папку dist/Muninhall (её упаковывает installer.iss).
# Запуск из корня репозитория:  pyinstaller packaging/windows/muninhall.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent.parent

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=collect_data_files("muninhall"),
    hiddenimports=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia",
                   "PySide6.QtSvg", "PySide6.QtPdf", "PySide6.QtTextToSpeech", "PySide6.QtNetwork",
                   "PySide6.QtDBus"],
    excludes=["tkinter", "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Muninhall",
          icon=str(ROOT / "muninhall" / "data" / "muninhall.ico"), console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Muninhall")
