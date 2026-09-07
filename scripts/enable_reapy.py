#!/usr/bin/env python3
"""
Enable the reapy distant API in REAPER.

Run this script from within REAPER:
  1. Open REAPER
  2. Go to Actions > Run ReaScript
  3. Select this file

After running, restart REAPER for the changes to take effect.
"""

import os
import sys
from pathlib import Path


# REAPER uses its embedded Python, so it does not automatically see the
# reaper-mcp virtual environment where reapy is installed. Add the local
# environment's pure-Python packages before importing reapy.
repo_root = Path(os.environ.get(
    "REAPER_MCP_ROOT",
    "/Users/poonv/Downloads/Repos/reaper-mcp",
))
site_package_roots = [repo_root / "venv312" / "lib", repo_root / "venv" / "lib"]
site_packages = []
for site_package_root in site_package_roots:
    site_packages.extend(site_package_root.glob("python*/site-packages"))
if site_packages:
    # Prefer Python 3.12 for REAPER's embedded Python compatibility.
    site_packages.sort(key=lambda path: ("python3.12" not in str(path), str(path)))
    sys.path.insert(0, str(site_packages[0]))

import reapy

reapy.config.enable_dist_api()
print("reapy distant API enabled. Please restart REAPER.")
