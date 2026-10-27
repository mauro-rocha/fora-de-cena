"""Small platform adapter: everything that differs between Windows and macOS lives here."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

# Tk falls back silently to a default family; pick one that exists on each system.
UI_FONT = 'Segoe UI' if IS_WINDOWS else ('Helvetica Neue' if IS_MAC else 'DejaVu Sans')

# Virtual camera backends that PyVirtualCam actually supports on this system.
VIRTUAL_BACKENDS: dict[str, str] = {'Só prévia': 'off', 'OBS Virtual Camera': 'obs'}
if IS_WINDOWS:
    VIRTUAL_BACKENDS['Unity Capture'] = 'unitycapture'

SYSTEM_NAME = 'Windows' if IS_WINDOWS else ('macOS' if IS_MAC else 'sistema')

if IS_MAC:
    CAMERA_PERMISSION_HINT = ('No macOS, libere a câmera em Ajustes do Sistema → Privacidade e Segurança → Câmera '
                              'para o Terminal (ou o app que abriu o Fora de Cena) e abra o app de novo.')
else:
    CAMERA_PERMISSION_HINT = 'Confira também a permissão de câmera nas configurações do Windows.'


def open_path(path: str | Path) -> None:
    """Open a file or folder with the system's default handler."""
    if IS_WINDOWS:
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif IS_MAC:
        subprocess.run(['open', str(path)], check=True, timeout=10)
    else:
        subprocess.run(['xdg-open', str(path)], check=True, timeout=10)


def user_data_base() -> Path:
    """Per-user writable folder for packaged builds."""
    if IS_MAC:
        return Path.home() / 'Library' / 'Application Support'
    local = os.environ.get('LOCALAPPDATA')
    return Path(local) if local else Path.home() / 'AppData' / 'Local'


def camera_apis() -> tuple[int, ...]:
    import cv2
    if IS_WINDOWS:
        return (cv2.CAP_DSHOW, cv2.CAP_MSMF)
    if IS_MAC:
        return (cv2.CAP_AVFOUNDATION,)
    return (cv2.CAP_V4L2,)


def enumeration_api() -> int:
    return camera_apis()[0]
