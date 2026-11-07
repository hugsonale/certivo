"""Run first, from the ml folder:  python scripts/check_environment.py   (it says whether this Python can run the workspace)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from certivo_ml.environment import main  # noqa: E402

raise SystemExit(main())
