"""Pytest configuration.

Sets the environment variables (API_KEYS, DB_PATH) before any module imports
stand_allocation.api, because the module-level app = create_app() reads
settings when it is imported (section 13.2).
"""

from __future__ import annotations

import os
import tempfile

os.environ["API_KEYS"] = "testkey01234567890123456789012345678901"
os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), "stand_allocation_test.db")
os.environ["BUFFER_MINUTES"] = "15"
os.environ["ALLOCATOR"] = "cpsat"
os.environ["LOG_LEVEL"] = "WARNING"
