"""Start Jarvis through the root supervisor; preserve manager stop signals."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
os.execv(sys.executable, [sys.executable, str(root / "start.py"), "--services", "jarvis", *sys.argv[1:]])
