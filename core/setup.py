from pathlib import Path
from setuptools import find_packages, setup

# ``setup.py`` lives inside the ``core`` package directory. Prefix the
# discovered subpackages so an installed distribution exposes the same public
# imports used by the services: ``core.db_connector``.
packages = [
    "core",
    *[f"core.{package}" for package in find_packages(where=str(Path(__file__).parent), exclude=["tests*", "basic_test*"])],
]

setup(
    packages=packages,
    package_dir={"core": "."},
)
