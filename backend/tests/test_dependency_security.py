"""Regression guards for the dependency findings from CI run 40896715041.

These guards prevent known version regressions; they do not replace image scans.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("package", "minimum"),
    [
        ("next", (15, 5, 28)),
        ("eslint-config-next", (15, 5, 28)),
        ("nanoid", (3, 3, 18)),
        ("postcss", (8, 5, 18)),
        ("sharp", (0, 35, 5)),
        ("source-map-js", (1, 2, 2)),
        ("baseline-browser-mapping", (2, 11, 0)),
        ("browserslist", (4, 28, 7)),
        ("js-yaml", (4, 3, 2)),
        ("postcss-selector-parser", (6, 1, 5)),
    ],
)
def test_frontend_lock_excludes_reported_vulnerable_versions(package, minimum):
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    versions = [
        entry["version"]
        for path, entry in lock["packages"].items()
        if path.endswith(f"node_modules/{package}")
    ]
    assert versions, f"No lockfile entries found for {package}"
    for version in versions:
        assert "-" not in version, f"Do not substitute a prerelease for {package}"
        assert tuple(map(int, version.split("."))) >= minimum, (package, version)


def test_brace_expansion_security_floors_preserve_both_supported_major_versions():
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    versions = [
        entry["version"]
        for path, entry in lock["packages"].items()
        if path.endswith("node_modules/brace-expansion")
    ]
    assert versions
    for version in versions:
        parts = tuple(map(int, version.split(".")))
        minimum = (1, 1, 21) if parts[0] == 1 else (5, 0, 12)
        assert parts >= minimum, version


def test_runtime_does_not_ship_pip_vendored_dependencies():
    dockerfile = (ROOT / "backend/Dockerfile").read_text()
    install = dockerfile.index("pip install --no-cache-dir -e .")
    assert "pip check" in dockerfile[install:]
    assert "pip uninstall --yes pip" in dockerfile[install:]


def test_backend_security_constraints_apply_to_image_and_ci():
    constraints = ROOT / "backend/constraints-security.txt"
    assert constraints.is_file()
    content = constraints.read_text()
    for floor in ("msgpack>=1.2.3", "urllib3>=2.8.0", "setuptools>=78.1.1"):
        assert floor in content
    for path in (ROOT / "backend/Dockerfile", ROOT / ".github/workflows/ci.yml"):
        assert "-c constraints-security.txt" in path.read_text()
