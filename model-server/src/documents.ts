/**
 * One record per open model document, and the one place the choice between
 * feeding the service edits and handing it text is made.
 *
 * `data-model.md` names the record `ModelDocument`: `uri`, `version`, `handle`
 * and the negotiated `encoding`. The text itself is kept by
 * `vscode-languageserver-textdocument`, which applies the incremental changes
 * the editor sends. Nothing here reads the text; it stores it, hands it over,
 * and reports which version it is.
 *
 * WHY THERE IS A BRANCH IN `update`
 *
 * `contracts/language-service-expected.md` records two ways the service could
 * take a document. Preferred: it holds a handle for the text and accepts an
 * edit against it, so a one-character change does not re-read the file.
 * Fallback: it accepts only text, and this repository hands over the current
 * text on each request.
 *
 * WHAT DECIDES IT: whether `@idfkit/language`, when it ships, exposes a
 * per-document handle that accepts an edit. Feature 005's contract as written
 * does not. Its five answers are pure functions of text, and it says so on
 * purpose: "neither group takes a service object, because a service object is
 * where state would accumulate". So the fallback is the live branch today,
 * `handle` is undefined, and `textOf` is what a handler calls. If 005 grows a
 * handle, `attach` installs one, the other side of the branch in `update`
 * starts running, and nothing outside this file changes. That last part is why
 * the branch is here rather than spread through the handlers.
 */

import { TextDocument } from 'vscode-languageserver-textdocument';

import type { TextDocumentContentChangeEvent } from 'vscode-languageserver-textdocument';
import type { PositionEncodingKind } from 'vscode-languageserver';

/**
 * The service's own state for one document, if it ever holds one.
 *
 * Declared as the seam the contract describes rather than as a guess at the
 * package's types: one method, taking exactly the changes the editor already
 * sent. Until `@idfkit/language` ships something to put here, no handle is ever
 * attached and this interface has no implementations.
 */
export interface ServiceHandle {
  /** Apply changes the editor sent, so the service need not re-read the text. */
  applyChanges(changes: readonly TextDocumentContentChangeEvent[], version: number): void;
}

/** What a handler sees. A snapshot, so it cannot be mutated under an answer. */
export interface ModelDocument {
  /** The editor's identifier for the document. */
  readonly uri: string;
  /** The editor's document version. A stale answer is dropped rather than sent. */
  readonly version: number;
  /** The current text, which is what the service takes. */
  readonly text: string;
  /** The unit the client negotiated, and the only input to translation besides the text. */
  readonly encoding: PositionEncodingKind;
  /** The service's state for this text, when it holds one. Undefined today. */
  readonly handle: ServiceHandle | undefined;
}

interface OpenDocument {
  readonly document: TextDocument;
  handle: ServiceHandle | undefined;
}

/** The default until `initialize` says otherwise, and what the protocol requires of every client. */
const DEFAULT_ENCODING: PositionEncodingKind = 'utf-16';

/**
 * Every open model document, keyed by URI.
 *
 * A URI this store does not hold is answered with nothing, which is the correct
 * answer to a request about a document the editor has closed. Reconstructing
 * one from a previous state would be exactly the guess Principle IV forbids.
 */
export class ModelDocuments {
  readonly #open = new Map<string, OpenDocument>();
  #encoding: PositionEncodingKind = DEFAULT_ENCODING;

  /** Record what the client and server settled on during initialisation. */
  negotiate(encoding: PositionEncodingKind): void {
    this.#encoding = encoding;
  }

  /** The negotiated unit, for a handler that needs it without a document. */
  get encoding(): PositionEncodingKind {
    return this.#encoding;
  }

  /** URIs currently open, in the order they were opened. */
  get uris(): readonly string[] {
    return [...this.#open.keys()];
  }

  open(uri: string, languageId: string, version: number, text: string): ModelDocument {
    const entry: OpenDocument = {
      document: TextDocument.create(uri, languageId, version, text),
      handle: undefined,
    };
    this.#open.set(uri, entry);
    return this.#snapshot(entry);
  }

  /**
   * Apply the editor's changes, incremental or full.
   *
   * Returns nothing for a URI that is not open, rather than opening one: an
   * edit to a document this server was never told about is a protocol fault,
   * and inventing the text before the first change is a guess.
   */
  update(
    uri: string,
    changes: readonly TextDocumentContentChangeEvent[],
    version: number,
  ): ModelDocument | undefined {
    const entry = this.#open.get(uri);
    if (entry === undefined) return undefined;

    TextDocument.update(entry.document, [...changes], version);

    // THE ONE BRANCH. See the note at the top of this file for what decides it.
    if (entry.handle === undefined) {
      // Text only. Nothing to feed; `textOf` hands over the current text on
      // each request and the cost of reading it is the service's.
    } else {
      entry.handle.applyChanges(changes, version);
    }

    return this.#snapshot(entry);
  }

  close(uri: string): void {
    this.#open.delete(uri);
  }

  /** Install the service's handle for a document, when the service holds one. */
  attach(uri: string, handle: ServiceHandle): boolean {
    const entry = this.#open.get(uri);
    if (entry === undefined) return false;
    entry.handle = handle;
    return true;
  }

  /** The document, or nothing at all when it is not open. */
  get(uri: string): ModelDocument | undefined {
    const entry = this.#open.get(uri);
    return entry === undefined ? undefined : this.#snapshot(entry);
  }

  /** The current text, which is what every call to the service carries. */
  textOf(uri: string): string | undefined {
    return this.#open.get(uri)?.document.getText();
  }

  /** The editor's version, for a handler about to answer or about to drop one. */
  versionOf(uri: string): number | undefined {
    return this.#open.get(uri)?.document.version;
  }

  /**
   * Whether an answer computed against `version` must be dropped.
   *
   * True when the document has moved on and true when it has closed, because
   * both mean the answer would land on text the editor no longer has. The
   * comparison is inequality rather than "greater than" so that a document
   * closed and reopened at a lower version is caught too.
   */
  isSuperseded(uri: string, version: number): boolean {
    const entry = this.#open.get(uri);
    return entry === undefined || entry.document.version !== version;
  }

  #snapshot(entry: OpenDocument): ModelDocument {
    return {
      uri: entry.document.uri,
      version: entry.document.version,
      text: entry.document.getText(),
      encoding: this.#encoding,
      handle: entry.handle,
    };
  }
}
