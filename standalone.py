#!/usr/bin/env python3
"""Standalone entrypoint, runnable as a script or module."""
import sys
from pathlib import Path

if __package__:
    from .gpu_inspector.applet import run_standalone
else:
    parent = str(Path(__file__).resolve().parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    from linspectacles_gpu_inspector.gpu_inspector.applet import run_standalone

if __name__ == '__main__':
    raise SystemExit(run_standalone())
