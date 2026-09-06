# Specification Quality Checklist: Two Servers, One Client, One Capability Story

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-04
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`.
- Validation passed on the first iteration. Two points were checked deliberately rather than
  waved through:
  - **Implementation details**: the spec names no language, framework, or protocol product. It
    uses *the first language* and *the second language*, the vocabulary features 001 through 005
    of the unification already established, which is defined once by how each installs. That
    definitional use of `pip` and `npm` is a naming convention carried over from the sibling
    specs, not a technology choice made here.
  - **Technology-agnostic success criteria**: SC-012 names a frame budget rather than a request
    latency, and SC-006 measures the characters a user sees selected rather than any internal
    structure. "Protocol" appears throughout because it is this repository's subject matter, not
    an implementation decision: the constitution's scope line is that this repository owns
    protocol and not knowledge.
- Constitution alignment was checked per principle: I (FR-024 to FR-027, US6), II (FR-001 to
  FR-007, FR-015 to FR-017, US1 and US3), III (FR-008 to FR-014, US2), IV (FR-021, FR-026,
  FR-003), V (FR-028 to FR-032, US7), VI (FR-033 to FR-037, US5).
- Three stories carry an external dependency on feature 005 of the unification landing the
  language service in the second language's repository. Stories 1, 2, 6, and 7 do not, and are
  the ones to sequence first if that dependency slips.

## Re-validation against the delivered work

**Date**: 2026-09-04, after implementation. No marker changed, because none needed to: every item
was already satisfied and the delivered work did not contradict any of them. What follows is what
was checked rather than assumed.

- **Requirements are testable**: every functional requirement now has something mechanical behind
  it. FR-006 is `tools/check_declaration.py` regenerating the readme block; FR-012 is
  `tools/check_levels.py` naming both files on a disagreement; FR-021 is `model-server/src/absence.ts`
  and the completion handler's tests; FR-024 to FR-027 are `tools/check_knowledge.py`; FR-031 and
  FR-035 are `tests/protocol/test_no_client.py` and `test_declaration.py`.
- **Success criteria are measurable, and were measured**: SC-012's budget reports a median of 0.8 ms
  at the protocol boundary for the source server, against 16.7 ms for one frame at 60 hertz. The
  model server's half of that measurement skips until the language service ships.
- **Scope was bounded, and held**: two additions beyond the task list were made and both are
  recorded in tasks.md progress notes rather than absorbed silently. Nothing else was widened.
- **Dependencies and assumptions identified**: the external dependency the notes above predicted is
  exactly the one that bit. Feature 005's language service does not exist, so the three stories that
  depend on it deliver everything except their two declaration flips, and stories 1, 2, 6 and 7
  delivered whole. `contracts/language-service-expected.md` did its job: reconciling it is one
  document rather than a shape spread through handlers.
