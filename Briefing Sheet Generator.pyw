"""Double-click to open the Flight Crew Briefing Sheet Generator.

A flight plan PDF dropped onto this file is opened straight away.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from briefsheet.gui import main  # noqa: E402

main(sys.argv[1] if len(sys.argv) > 1 else None)
