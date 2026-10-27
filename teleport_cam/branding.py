"""Application identity and icon; no changes to system-wide settings."""
import os
import tkinter as tk
from .paths import resource_root

ICON=resource_root()/'assets'/'brand'/'app-icon.ico'
ICON_PNG=resource_root()/'assets'/'brand'/'app-icon.png'


def set_process_identity() -> None:
    if os.name=='nt':
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ForaDeCena.Desktop')
        except (OSError,AttributeError):
            pass


def set_window_icon(window:tk.Tk | tk.Toplevel) -> None:
    if os.name!='nt':
        # .ico is Windows-only; Tk on macOS/Linux takes a PNG photo image instead.
        if ICON_PNG.is_file():
            try:
                image=tk.PhotoImage(master=window,file=str(ICON_PNG))
                window.iconphoto(True,image)
                window._fora_de_cena_icon=image  # keep a reference so Tk does not drop it
            except (tk.TclError,OSError):
                pass
        return
    if ICON.is_file():
        try:
            # CustomTkinter sees this explicit call and retains our icon after its startup timer.
            window.iconbitmap(default=str(ICON))
        except (tk.TclError,OSError):
            pass
