"""The script that PyInstaller freezes: ``reframe-server``."""

import sys

from reframe_server.__main__ import main

sys.exit(main())
