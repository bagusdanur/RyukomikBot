import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pre-import top-level helpers package to prevent shadowing from dashboard.backend.helpers
import helpers
import helpers.utils
