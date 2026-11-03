"""Shared test setup."""

import os

# App tests run the real app; keep their sessions out of the business dashboards.
os.environ["HALFTIME_NO_TRACKING"] = "1"
