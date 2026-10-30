"""The gate fails when something the suite needs is missing, and a direct run still skips.

A passing ``make check`` is evidence only if the protocol tests ran. These tests hold the rule in
``conftest.py`` and the two places that turn it on, because removing either leaves every other test
passing while the gate quietly goes back to skipping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .conftest import MODEL_SERVER_PACKAGE, REPOSITORY_ROOT, REQUIRE_FULL_SUITE, skip_or_fail

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def direct_run(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """The environment of a direct ``pytest`` run from a checkout, whatever this run's is."""
    monkeypatch.delenv(REQUIRE_FULL_SUITE, raising=False)
    monkeypatch.delenv(MODEL_SERVER_PACKAGE, raising=False)
    return monkeypatch


class TestWhatAnAbsenceBecomes:
    def test_a_direct_run_from_a_checkout_skips(self, direct_run: pytest.MonkeyPatch) -> None:
        with pytest.raises(pytest.skip.Exception, match="the reason"):
            skip_or_fail("the reason")

    def test_a_run_that_must_be_complete_fails(self, direct_run: pytest.MonkeyPatch) -> None:
        direct_run.setenv(REQUIRE_FULL_SUITE, "1")
        with pytest.raises(pytest.fail.Exception, match="the reason"):
            skip_or_fail("the reason")

    def test_an_empty_requirement_is_not_a_requirement(
        self, direct_run: pytest.MonkeyPatch
    ) -> None:
        direct_run.setenv(REQUIRE_FULL_SUITE, "")
        with pytest.raises(pytest.skip.Exception, match="the reason"):
            skip_or_fail("the reason")

    def test_a_packaged_run_fails(self, direct_run: pytest.MonkeyPatch, tmp_path: Path) -> None:
        direct_run.setenv(MODEL_SERVER_PACKAGE, str(tmp_path))
        with pytest.raises(pytest.fail.Exception, match="the reason"):
            skip_or_fail("the reason")


class TestTheGateTurnsTheRuleOn:
    def test_the_makefile_builds_the_model_server_and_requires_a_complete_run(self) -> None:
        makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
        assert f"test-protocol: export {REQUIRE_FULL_SUITE} := 1" in makefile
        assert "test-protocol: build-model" in makefile

    def test_continuous_integration_requires_a_complete_run(self) -> None:
        workflow = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
        assert f'{REQUIRE_FULL_SUITE}: "1"' in workflow.read_text(encoding="utf-8")
