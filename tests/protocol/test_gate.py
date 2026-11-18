"""The gate fails when something the suite needs is missing, and a direct run still skips.

A passing ``make check`` is evidence only if the protocol tests ran. These tests hold the rule in
``conftest.py`` and the two places that turn it on, because removing either leaves every other test
passing while the gate quietly goes back to skipping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import MODEL_SERVER_PACKAGE, REPOSITORY_ROOT, REQUIRE_FULL_SUITE, skip_or_fail

# The spellings that skip a test without passing through ``skip_or_fail``.
_DIRECT_SKIPS = ("pytest.skip(", "pytest.mark.skip", "pytest.importorskip(")


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

    def test_the_command_a_change_is_held_to_runs_the_protocol_suite(self) -> None:
        makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
        check = next(line for line in makefile.splitlines() if line.startswith("check:"))
        assert "test-protocol" in check.partition("##")[0].split()

    def test_continuous_integration_requires_a_complete_run_in_every_job(self) -> None:
        workflow = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
        text = workflow.read_text(encoding="utf-8")
        assert f'\nenv:\n  {REQUIRE_FULL_SUITE}: "1"\n' in text


class TestNoSkipGoesAroundTheRule:
    def test_only_the_rule_and_a_declared_absence_skip_directly(self) -> None:
        """A direct skip stays a skip under ``REQUIRE_FULL_SUITE``, so each one has to be counted.

        ``conftest.py`` holds the rule's own skip. ``test_budget.py`` skips a capability the
        declaration records as absent. A new entry either goes through ``skip_or_fail`` or is
        another declared absence, and this count is changed only in the second case.
        """
        suite = REPOSITORY_ROOT / "tests" / "protocol"
        found: dict[str, int] = {}
        for path in sorted(suite.glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            count = sum(text.count(form) for form in _DIRECT_SKIPS)
            if count:
                found[path.name] = count
        assert found == {"conftest.py": 1, "test_budget.py": 1}
