"""The separation in release.yml, read from the parsed workflow, since no release can run in a test.

A regression here costs nothing until a release runs, and then it costs a credential: a step added
to a publish job looks like any other step. So this holds what a reviewer would otherwise have to
remember. It says nothing about whether the workflow publishes, which only a release can show.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from .._common import repository_root

if TYPE_CHECKING:
    from pathlib import Path

WORKFLOWS = repository_root() / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
REHEARSAL = WORKFLOWS / "release-rehearsal.yml"
VSCE_LOCK = repository_root() / ".github" / "vsce" / "package-lock.json"

# Each publish job, with the job that builds and checks its file, and the artifact between them.
PAIRS = {
    "publish": ("package-wheel", "wheel"),
    "publish-npm": ("package-npm", "npm-tarball"),
    "publish-vsix": ("package-vsix", "vsix"),
}
NO_CHECKOUT = ("publish", "publish-npm")
VSCE_DIRECTORY = ".github/vsce"
VSCE_CHECKOUT_PATHS = ["/.github/vsce/package.json", "/.github/vsce/package-lock.json"]
VSCE_INSTALL = "npm ci --ignore-scripts --no-audit --no-fund"

INSTALLS_OR_BUILDS = re.compile(
    r"\b(npm\s+(ci|install|i|pack|exec|run|rebuild)|npx|uvx|uv\s+(sync|build|run|pip|tool|add)"
    r"|pip3?\s+install|python3?\s+-m\s+pip|yarn|pnpm|make)\b"
)
PINNED = re.compile(r"^\s*(?:- )?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+\s*$")
USES = re.compile(r"^\s*(?:- )?uses:")


@dataclass(frozen=True)
class Step:
    uses: str
    run: str
    name: str
    working_directory: str
    inputs: dict[str, Any]

    @property
    def action(self) -> str:
        return self.uses.partition("@")[0]


@dataclass(frozen=True)
class Job:
    name: str
    permissions: dict[str, str]
    needs: tuple[str, ...]
    condition: str
    steps: tuple[Step, ...]

    def using(self, action: str) -> list[Step]:
        return [step for step in self.steps if step.action == action]


def load_jobs(path: Path) -> dict[str, Job]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs: dict[str, Job] = {}
    for name, body in document["jobs"].items():
        needs = body.get("needs", ())
        jobs[name] = Job(
            name=name,
            permissions=body.get("permissions", document["permissions"]),
            needs=(needs,) if isinstance(needs, str) else tuple(needs),
            condition=body.get("if", ""),
            steps=tuple(
                Step(
                    uses=step.get("uses", ""),
                    run=step.get("run", ""),
                    name=step.get("name", ""),
                    working_directory=step.get("working-directory", ""),
                    inputs=step.get("with", {}),
                )
                for step in body["steps"]
            ),
        )
    return jobs


@pytest.fixture(scope="module")
def release() -> dict[str, Job]:
    return load_jobs(RELEASE)


@pytest.fixture(scope="module")
def rehearsal() -> dict[str, Job]:
    return load_jobs(REHEARSAL)


def test_only_the_publish_jobs_can_request_a_token(release: dict[str, Job]) -> None:
    holders = {name for name, job in release.items() if "id-token" in job.permissions}
    assert holders == set(PAIRS)
    assert "id-token" not in yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["permissions"]


def test_the_workflow_runs_only_on_a_published_release() -> None:
    # PyYAML reads the bare key `on` as a boolean.
    triggers = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))[True]
    assert triggers == {"release": {"types": ["published"]}}


@pytest.mark.parametrize("publish", PAIRS)
def test_each_publish_job_receives_its_file_from_its_package_job(
    release: dict[str, Job], publish: str
) -> None:
    package, artifact = PAIRS[publish]
    assert release[publish].needs == (package,)

    uploads = release[package].using("actions/upload-artifact")
    downloads = release[publish].using("actions/download-artifact")
    assert [step.inputs["name"] for step in uploads] == [artifact]
    assert uploads[0].inputs["if-no-files-found"] == "error"
    assert [step.inputs["name"] for step in downloads] == [artifact]


@pytest.mark.parametrize("publish", PAIRS)
def test_a_package_job_refuses_a_wrong_tag_and_finishes_checking_before_the_handoff(
    release: dict[str, Job], publish: str
) -> None:
    package = release[PAIRS[publish][0]]
    upload = package.steps.index(package.using("actions/upload-artifact")[0])
    refusal = [
        index
        for index, step in enumerate(package.steps)
        if step.name.startswith("Refuse a release")
    ]
    assert len(refusal) == 1
    assert refusal[0] < upload
    assert "id-token" not in package.permissions

    # The attachment to the release follows the handoff, and checks nothing.
    checks = [
        index
        for index, step in enumerate(package.steps)
        if re.search(r"check_package|zipfile|tests/protocol", step.run)
    ]
    assert checks, f"{package.name} checks nothing"
    assert max(checks) < upload


@pytest.mark.parametrize("publish", NO_CHECKOUT)
def test_the_pypi_and_npm_publish_jobs_have_no_checkout_and_install_nothing(
    release: dict[str, Job], publish: str
) -> None:
    job = release[publish]
    assert job.using("actions/checkout") == []
    assert job.permissions == {"id-token": "write"}
    for step in job.steps:
        assert not INSTALLS_OR_BUILDS.search(step.run), step.run


def test_publish_runs_uv_at_a_stated_level_with_no_cache(release: dict[str, Job]) -> None:
    setup = release["publish"].using("astral-sh/setup-uv")[0]
    assert re.fullmatch(r"\d+\.\d+\.\d+", setup.inputs["version"])
    assert setup.inputs["enable-cache"] is False


def test_publish_vsix_fetches_two_files_and_installs_only_the_locked_tree(
    release: dict[str, Job],
) -> None:
    job = release["publish-vsix"]
    checkouts = job.using("actions/checkout")
    assert len(checkouts) == 1
    assert checkouts[0].inputs["persist-credentials"] is False
    assert checkouts[0].inputs["sparse-checkout-cone-mode"] is False
    assert checkouts[0].inputs["sparse-checkout"].split() == VSCE_CHECKOUT_PATHS

    installing = [step for step in job.steps if INSTALLS_OR_BUILDS.search(step.run)]
    assert [(step.run.strip(), step.working_directory) for step in installing] == [
        (VSCE_INSTALL, VSCE_DIRECTORY)
    ]


def test_vsce_comes_only_from_the_lockfile(release: dict[str, Job]) -> None:
    for job in release.values():
        for step in job.steps:
            assert "npx" not in step.run, f"{job.name} runs an unlocked tool: {step.run}"
    package = release["package-vsix"]
    assert (VSCE_INSTALL, VSCE_DIRECTORY) in [
        (step.run.strip(), step.working_directory) for step in package.steps
    ]


def test_the_rehearsal_can_never_request_a_token(rehearsal: dict[str, Job]) -> None:
    assert yaml.safe_load(REHEARSAL.read_text(encoding="utf-8"))["permissions"] == {
        "contents": "read"
    }
    for job in rehearsal.values():
        assert "id-token" not in job.permissions, job.name


def test_the_rehearsal_publishes_only_as_a_dry_run(rehearsal: dict[str, Job]) -> None:
    for job in rehearsal.values():
        for step in job.steps:
            if re.search(r"\b(uv|npm) publish\b", step.run):
                assert "--dry-run" in step.run, step.run


def test_the_rehearsal_uses_the_actions_and_the_uv_of_the_release(
    release: dict[str, Job], rehearsal: dict[str, Job]
) -> None:
    def actions(jobs: dict[str, Job]) -> set[str]:
        return {step.uses for job in jobs.values() for step in job.steps if step.uses}

    assert actions(rehearsal) == actions(release)
    assert (
        rehearsal["rehearse-wheel"].using("astral-sh/setup-uv")[0].inputs["version"]
        == release["publish"].using("astral-sh/setup-uv")[0].inputs["version"]
    )


@pytest.mark.parametrize("path", [RELEASE, REHEARSAL], ids=lambda path: path.name)
def test_every_action_is_pinned_to_a_commit_with_its_version_beside_it(path: Path) -> None:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if USES.match(line)]
    assert lines
    for line in lines:
        assert PINNED.match(line), line


def test_the_vsce_lockfile_holds_every_package_to_the_registry_and_a_hash() -> None:
    lock = json.loads(VSCE_LOCK.read_text(encoding="utf-8"))
    packages = {name: body for name, body in lock["packages"].items() if name}

    assert (
        lock["packages"][""]["dependencies"]["@vscode/vsce"]
        == (packages["node_modules/@vscode/vsce"]["version"])
    )
    for name, body in packages.items():
        assert body["resolved"].startswith("https://registry.npmjs.org/"), name
        assert body["integrity"].startswith("sha512-"), name

    # The runner is Linux, and a lockfile written elsewhere can omit another platform's package.
    assert "node_modules/@vscode/vsce-sign-linux-x64" in packages
