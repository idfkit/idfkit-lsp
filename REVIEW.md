# Code Review: idfkit-lsp

## Overall Assessment

Well-structured LSP server for Python-based EnergyPlus development with idfkit.
Clean architecture: thin protocol wiring in `server.py`, separated providers per
LSP feature, standalone AST-based type inference engine, and a schema caching layer.
Readable code, solid test suite (64 tests, all passing), modern Python tooling
(uv, ruff, pyright, pytest). Linting and type checking pass cleanly.

---

## Bugs

### 1. `version or 0` treats version `0` as `None`

**Files:** `server.py:84`, `server.py:98`

```python
_docs.update(td.uri, td.text, td.version or 0)
```

The LSP spec defines `version` as an integer starting at 0. Since `0` is falsy in
Python, `td.version or 0` conflates a legitimate version `0` with a missing value.
In practice the result is the same (`0`), but the intent is unclear and this pattern
would break if version semantics ever mattered beyond caching. Use an explicit check:

```python
td.version if td.version is not None else 0
```

### 2. `_count_parameters` doesn't handle escape sequences

**File:** `signature_help.py:157-175`

The parameter counter tracks whether the cursor is inside a string but doesn't
handle backslash escapes. A string argument like `"value with \" inside"` causes
the parser to exit the string at the escaped quote, miscounting subsequent commas
and producing an incorrect `active_parameter` index.

---

## Dead Code

### 3. `_object_type_lower` dict is built but never queried

**File:** `schema_cache.py:27`

```python
self._object_type_lower: dict[str, str] = {ot.lower(): ot for ot in self._object_types}
```

This mapping is computed at construction time but never referenced anywhere.
`match_object_types` (line 77) does its own inline `.lower()` comparison. Either
remove this dict or refactor `match_object_types` to use it.

### 4. All functions in `utils.py` are unused

**File:** `utils.py:1-38`

None of `get_line_text`, `get_word_at_position`, or `safe_parse` are imported or
called anywhere in the server source. The server extracts lines inline in handlers,
and the analyzer has its own `_robust_parse`. This entire module is dead code.

---

## Performance

### 5. `get_bindings_at_line` re-parses the document on every LSP request

**File:** `document_state.py:65-74`

```python
def get_bindings_at_line(self, uri: str, line: int) -> dict[str, InferredType]:
    state = self._states.get(uri)
    if not state:
        return {}
    analyzer = IdfKitAnalyzer()
    return analyzer.analyze_at_line(state.source, line)
```

Every completion, hover, and signature help request creates a new `IdfKitAnalyzer`
and re-parses the document AST from scratch. The `update()` method already performs
a full analysis and caches bindings, but this line-scoped version doesn't reuse that
work. For large EnergyPlus scripts (hundreds of zone/surface setup lines), parsing
the AST on every keystroke adds up.

Consider caching the parsed AST in `DocumentState` and reusing it, or using the
pre-computed full bindings with a line-based filter.

### 6. `lru_cache` on a bound method

**File:** `schema_cache.py:70-73`

`@lru_cache(maxsize=128)` on `describe()` captures `self` in the cache key, which
prevents garbage collection of `SchemaCache` instances. The ruff `B019` ignore
acknowledges this. Since `SchemaCache` is effectively a singleton this works, but if
the server ever supported multiple schema versions per-workspace, this would leak.

---

## Design & Architecture

### 7. Module-level mutable globals for server state

**File:** `server.py:51-52`

```python
_schema: SchemaCache | None = None
_docs: DocumentStateManager | None = None
```

State held in module-level globals mutated via `global`. Common in pygls servers,
but makes unit testing of handler functions harder and prevents running multiple
server instances in-process. Consider attaching state to the server instance via
subclassing `LanguageServer` or using pygls's workspace data.

### 8. `_robust_parse` only drops trailing lines

**File:** `analyzer.py:88-111`

Handles the common case of incomplete code at the cursor line. But if the syntax
error is mid-file (user editing line 5 of a 100-line file), it fails because it only
tries removing up to 4 lines from the bottom. A fallback that tries a binary-search
truncation strategy would improve resilience for non-bottom editing.

---

## Client Extension

### 9. Output channels not disposed

**File:** `client/src/extension.ts:19-24`

`outputChannel` and `traceOutputChannel` are created but not added to
`context.subscriptions`. They will leak on deactivation/reactivation.

### 10. `client.start()` return value not awaited

**File:** `client/src/extension.ts:39`

`client.start()` returns a Promise that is fire-and-forget. If the server fails to
start (Python not found, idfkit not installed), the error becomes an unhandled
promise rejection. Either `await` it or attach a `.catch()` handler.

---

## Test Coverage Gaps

### 11. No tests for `visit_With` (context manager inference)

**File:** `analyzer.py:245-252`

The analyzer handles `with` statements but no test exercises this path.

### 12. No tests for `visit_AsyncFunctionDef`

**File:** `analyzer.py:239`

Aliased to `visit_FunctionDef` but never tested with `async def`.

### 13. Integration tests rely on `time.sleep` for synchronization

**File:** `test_server_integration.py:125,154`

`time.sleep(1)` after initialization and `time.sleep(0.2)` after `didOpen` are
race conditions. On slow CI runners these can be insufficient; on fast machines
they waste time. Consider polling for a ready signal instead.

### 14. `_send_lsp` parameter shadows built-in `id`

**File:** `test_server_integration.py:13`

Minor: rename to `msg_id` or `request_id`.

---

## Minor Issues

### 15. `fcntl`/`os`/`select` imported inside function body

**File:** `test_server_integration.py:27-29`

These are Linux-only modules imported inside `_read_lsp`. Since the test is already
Linux-only (subprocess pipes with select), move imports to module level.

### 16. Missing `pytest-timeout` dependency

**File:** `pyproject.toml`

Dev dependencies don't include `pytest-timeout`, which would prevent hung
integration tests from blocking CI indefinitely.

### 17. Hover field-attr regex can match method names

**File:** `hover.py:58`

The regex `(\w+)\.(\w+)` matches any attribute access including `doc.add`. The
`is_object` guard at line 64 prevents false positives in most cases, but the pattern
is fragile.

### 18. No `textDocument/didSave` handler

**File:** `server.py`

Only `didOpen`, `didChange`, and `didClose` are handled. Some LSP clients can be
configured to sync only on save. Explicitly handling `didSave` would improve
compatibility.

---

## What's Done Well

- Clean module boundaries with single responsibility per file
- Regex-based completion/hover detection is pragmatic for incomplete code
- `_robust_parse` is a thoughtful solution for partial-edit resilience
- `SchemaCache` provides a clean interface over raw idfkit schema access
- Good test organization: per-module unit tests + end-to-end integration
- CI matrix across Python 3.10-3.13
- Comprehensive tooling: ruff + pyright + pre-commit
- Makefile provides a clean developer workflow
