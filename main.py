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

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

import theme
from main_window import MainWindow


def main():
    # El reproductor embebido (libmpv render API) necesita un contexto
    # OpenGL 3.3 core y que Qt comparta contextos entre widgets.
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Visuales UCLV")

    app.setStyleSheet(theme.build_stylesheet())

    window = MainWindow()
    window.show()
    code = app.exec()
    # Las descargas de portadas/subtítulos siguen en hilos del pool:
    # os._exit evita que el intérprete espere su join (la app quedaba
    # viva en el Dock unos segundos después de cerrar la ventana).
    os._exit(code)


if __name__ == "__main__":
    main()
