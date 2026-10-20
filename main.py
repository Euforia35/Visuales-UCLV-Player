#!/usr/bin/env python3
"""
Visuales UCLV — cliente de escritorio para macOS
--------------------------------------------------
Explora y reproduce en streaming el contenido de visuales.uclv.cu
sin pasar por el navegador.

Ejecutar en modo desarrollo:
    python3 main.py

Empaquetar como app de macOS (doble clic):
    python3 setup.py py2app
"""

import sys

from PySide6.QtWidgets import QApplication

import theme
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Visuales UCLV")

    app.setStyleSheet(theme.build_stylesheet())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
