"""Ponto de entrada do programa BRASIL+ (PyInstaller). Veja app/executavel.py."""
import multiprocessing
import sys

from app.executavel import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
