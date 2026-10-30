"""The package check's reading of a tarball, against archives built here."""

from __future__ import annotations

import io
import tarfile
from typing import TYPE_CHECKING

from .._common import Report
from ..check_package import EXPECTED_MEMBERS, _check_tarball

if TYPE_CHECKING:
    from pathlib import Path

BUNDLE_MEMBER = "package/dist/main.js"
DECLARATION_MEMBER = "package/dist/capabilities.json"
DECLARATION = b'{"version": 1}'


def _failures(tmp_path: Path, bundle: bytes) -> list[str]:
    """What the check says about a tarball carrying every expected member and this bundle."""
    (tmp_path / "capabilities.json").write_bytes(DECLARATION)
    tarball = tmp_path / "package.tgz"
    with tarfile.open(tarball, "w:gz") as archive:
        for name in sorted(EXPECTED_MEMBERS):
            content = {BUNDLE_MEMBER: bundle, DECLARATION_MEMBER: DECLARATION}.get(name, b"")
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    report = Report("check_package")
    _check_tarball(tmp_path, tarball, report)
    return report.failures


def test_a_bundle_naming_no_source_map_passes(tmp_path: Path) -> None:
    assert _failures(tmp_path, b"export const a = 1;\n") == []


def test_a_bundle_naming_a_source_map_fails(tmp_path: Path) -> None:
    failures = _failures(tmp_path, b"export const a = 1;\n//# sourceMappingURL=main.js.map\n")
    assert len(failures) == 1
    assert "source map" in failures[0]


def test_a_bundle_that_is_not_utf8_is_still_read(tmp_path: Path) -> None:
    assert _failures(tmp_path, b"\xff\xfe export const a = 1;\n") == []
