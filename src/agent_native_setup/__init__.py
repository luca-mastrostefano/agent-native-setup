"""Wizard that scaffolds an agent-native project setup."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-native-setup")
except PackageNotFoundError:  # running from a raw checkout, not installed
    __version__ = "0.0.0"
