"""``python -m sdk`` entry point (#390, ADR-0040)."""

import sys

from sdk.cli import main

sys.exit(main())
