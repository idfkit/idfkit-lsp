# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The packaged VS Code extension now carries the language service. A VSIX built with `vsce package`
  contained no `@idfkit` package, so the model server could not resolve `@idfkit/idfkit` and
  advertised no model text capability. The prepublish step now installs the model server's locked
  dependencies, and `.vscodeignore` keeps `@idfkit/idfkit`, `@idfkit/core`, `@idfkit/language` and
  `@idfkit/schemas` while leaving every other package in `model-server/node_modules` out. The npm
  package `@idfkit/language-server` is unchanged.

## [0.4.0] - 2026-10-30

The model server can now be installed from npm, so editors other than VS Code can run it without
cloning this repository. Neither server gains or loses a capability.

### Added

- The model server is published to npm as `@idfkit/language-server`, so an editor other than VS Code
  can install it without cloning this repository. Installing it puts `idfkit-language-server` on
  the path; run it with `--stdio`. The package carries its own copy of `capabilities.json`, made
  from the root file each time it is packed. Releases publish it beside the PyPI package, from the
  same tag (#33, #34).

### Changed

- The model server depends on `@idfkit/idfkit` 0.4.0, pinned exactly, and reaches the library and
  its language service only through that name. It no longer falls back to `@idfkit/core` and
  `@idfkit/language` under their own names, which it did while the facade was not on npm. A
  missing install now asks for `@idfkit/idfkit` and `@idfkit/language` (#34).
- The model server's package was renamed from `@idfkit/lsp-model-server` to
  `@idfkit/language-server`, which is also the name it reports in `serverInfo` (#34).

## [0.3.0] - 2026-10-19

This release moves both servers to the current library levels. Neither server gains or loses a
capability.

### Changed

- The source server now requires idfkit 1.1.1, pinned exactly (0.2.0 required 1.0.0rc1). Give it an
  environment of its own if your project runs a different idfkit.
- The model server now resolves `@idfkit/core` and `@idfkit/language` at 0.4.0 (0.2.0 resolved
  0.2.0).
- The model server looks for the idfkit facade as `@idfkit/idfkit`, and its subpaths as
  `@idfkit/idfkit/language` and `@idfkit/idfkit/node`, instead of `idfkit`. npm refused the unscoped
  name. Until the facade is published, the model server still falls back to `@idfkit/core` and
  `@idfkit/language` under their own names.

## [0.2.0] - 2026-09-11

The first release published to PyPI. `pip install idfkit-lsp` installs the source server, the
language server for Python code that uses idfkit.

### Added

- A second language server for EnergyPlus model text. It runs on the editor's own Node runtime,
  wraps `@idfkit/language`, and answers token classification, findings, completion, explanations and
  declaration lookup. It ships inside the editor extension; the PyPI package is the source server
  only.
- `capabilities.json`, the single declaration of what each server advertises. It travels inside the
  Python package, and the test suite holds both servers to it in both directions.
- An `idfkit-lsp/versions` request, which reports the server's version and the library levels it
  read.
- An MIT licence file, included in the published wheel.

### Changed

- The source server reads the calls that produce a document, and the type names it recognises, from
  the installed idfkit rather than from a table kept in this repository. A new idfkit release no
  longer needs a matching edit here.
- The source server now requires idfkit 1.0.0rc1, pinned exactly (0.1.0 used idfkit 0.8.0). Give it
  an environment of its own if your project runs a different idfkit.

### Fixed

- The package can be built and published. Building it previously failed, because the source
  distribution could not carry the `capabilities.json` the server reads at start-up.
- `idfkit_lsp.__version__` reported `0.1.0` in the 0.2.0 sources. It is now read from the installed
  distribution.
- When the language service is missing, the message now names `@idfkit/language`, which can be
  installed, instead of the `idfkit` npm package, which has not been published.

## [0.1.0] - 2026-04-16

The first release, published on GitHub with a VS Code extension.

### Added

- A language server for Python code that uses idfkit, and a VS Code extension that starts it.
- Completion for object type names, field attributes and keyword arguments, with each field's
  documentation, units and constraints.
- Hover documentation for object types, field attributes and inferred variables, with links to the
  EnergyPlus documentation.
- Signature help for `doc.add()` calls, listing required and optional fields.
- Type inference that follows `IDFDocument`, `IDFCollection` and `IDFObject` through assignments,
  subscripts, method calls and loops.
- An "Open Documentation" command in the VS Code extension.

[unreleased]: https://github.com/idfkit/idfkit-lsp/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/idfkit/idfkit-lsp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/idfkit/idfkit-lsp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/idfkit/idfkit-lsp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/idfkit/idfkit-lsp/releases/tag/v0.1.0
