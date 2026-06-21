import sys
from pathlib import Path

# Make `src/` importable so tests run without an install (matches the sibling linters).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
