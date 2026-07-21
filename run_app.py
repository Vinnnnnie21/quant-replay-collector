from __future__ import annotations

import os
import time

os.environ.setdefault(
    "QRC_PROCESS_START_PERF_COUNTER",
    str(time.perf_counter()),
)

from quant_collector_app.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
