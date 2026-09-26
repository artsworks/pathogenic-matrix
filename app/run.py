"""Start the Pathogenic Matrix companion app: python app/run.py --open"""

import sys
from pathlib import Path

if sys.version_info < (3, 10):  # noqa: UP036
    sys.exit("Pathogenic Matrix needs Python 3.10 or newer.")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from matrix.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
