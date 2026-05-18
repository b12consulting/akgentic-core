"""Test package initialization and structure."""

import importlib.metadata

import akgentic.core


def test_package_metadata() -> None:
    """Test that package metadata is accessible."""
    metadata = importlib.metadata.metadata("akgentic-core")
    assert metadata["Name"] == "akgentic-core"
    # Version is read from installed distribution metadata rather than
    # hardcoded so the test survives release bumps.
    assert metadata["Version"] == importlib.metadata.version("akgentic-core")


def test_package_has_all_attribute() -> None:
    """Test that __all__ is defined."""
    assert hasattr(akgentic.core, "__all__")
    assert "__version__" in akgentic.core.__all__
