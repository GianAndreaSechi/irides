from pathlib import Path
from setuptools import find_packages, setup

# ``setup.py`` lives inside the ``core`` package directory.
# Exposes both the canonical ``irides_core`` namespace and the backward-compatible
# ``core.db_connector`` imports used across existing services.
discovered = find_packages(
    where=str(Path(__file__).parent), exclude=["tests*", "basic_test*"]
)
packages = [
    "core",
    "irides_core",
    *[f"core.{package}" for package in discovered],
]

setup(
    packages=packages,
    package_dir={"core": ".", "irides_core": "irides_core"},
)
