from setuptools import find_packages, setup

setup(
    name="irides-cli",
    version="0.1.0",
    description="Command-line interface for Irides database introspection",
    packages=find_packages(include=["irides_cli*"]),
    install_requires=["irides-core>=0.1.0"],
    entry_points={"console_scripts": ["irides=irides_cli.main:main"]},
)
