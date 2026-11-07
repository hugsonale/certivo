"""Run from anywhere in the repository:  python ml/scripts/check_no_data.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from certivo_ml.guard import main  # noqa: E402

raise SystemExit(main())
