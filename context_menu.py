"""Ajoute / retire « Downscaler PSX » du menu clic droit de l'explorateur Windows.

    python context_menu.py              installe
    python context_menu.py --uninstall  désinstalle

Écrit uniquement dans HKEY_CURRENT_USER : pas besoin de droits administrateur.
Sous Windows 11, l'entrée apparaît dans « Afficher plus d'options » (Maj+F10).
"""

import sys
import winreg
from pathlib import Path

VERB_KEY = "DownscalerPSX"
MENU_LABEL = "Downscaler PSX"
EXTENSIONS = (".png", ".jpg", ".jpeg")
SCRIPT = Path(__file__).resolve().parent / "downscaler_gui.py"


def pythonw_path() -> Path:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def verb_path(ext: str) -> str:
    return rf"Software\Classes\SystemFileAssociations\{ext}\shell\{VERB_KEY}"


def install():
    pyw = pythonw_path()
    command = f'"{pyw}" "{SCRIPT}" "%1"'
    for ext in EXTENSIONS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, verb_path(ext)) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, MENU_LABEL)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, str(pyw))
            # Sans limite de 15 fichiers sélectionnés.
            winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, verb_path(ext) + r"\command") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, command)
    print(f"Installé pour {', '.join(EXTENSIONS)}")
    print(f"Commande : {command}")


def uninstall():
    for ext in EXTENSIONS:
        for sub in (r"\command", ""):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, verb_path(ext) + sub)
            except FileNotFoundError:
                pass
    print("Entrée du menu contextuel retirée.")


if __name__ == "__main__":
    if "--uninstall" in sys.argv[1:]:
        uninstall()
    else:
        install()
