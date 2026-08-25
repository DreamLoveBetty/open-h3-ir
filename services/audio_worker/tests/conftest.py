"""Make the worker package importable when pytest runs from the repository root.

The worker is a service, not part of the installed `h3ir` package, so its tests put its parent
on sys.path themselves rather than asking the project's packaging to know about it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
