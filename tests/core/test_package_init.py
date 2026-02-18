"""Test package initialization and structure."""

import importlib.metadata

import akgentic


def test_package_version() -> None:
    """Test that package version is correctly set."""
    assert akgentic.__version__ == "1.0.0-alpha.1"


def test_package_metadata() -> None:
    """Test that package metadata is accessible."""
    metadata = importlib.metadata.metadata("akgentic")
    assert metadata["Name"] == "akgentic"
    # Python normalizes "alpha.1" to "a1" in package version
    assert metadata["Version"] == "1.0.0a1"


def test_package_has_all_attribute() -> None:
    """Test that __all__ is defined."""
    assert hasattr(akgentic, "__all__")
    assert "__version__" in akgentic.__all__


def test_minimal_dependencies() -> None:
    """Test that package has only essential runtime dependencies."""
    # Check pyproject.toml dependencies via metadata
    metadata = importlib.metadata.metadata("akgentic")
    requires = metadata.get_all("Requires-Dist") or []

    # Filter out dev dependencies (extras)
    runtime_deps = [dep for dep in requires if "extra ==" not in dep]

    # Only pydantic is required for serialization
    allowed_deps = {"pydantic"}
    for dep in runtime_deps:
        dep_name = dep.split(">=")[0].split("[")[0].strip().lower()
        assert dep_name in allowed_deps, f"Unexpected dependency: {dep}"

    assert len(runtime_deps) <= len(allowed_deps), f"Too many dependencies: {runtime_deps}"
