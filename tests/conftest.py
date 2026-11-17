import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bmw_logbook" / "app"))

import os

os.environ.setdefault("TZ", "Europe/Helsinki")
