/**
 * Classification, delivered as `textDocument/semanticTokens/full`.
 *
 * The service classifies the whole text and this file re-expresses that classification in the
 * protocol's encoding. Nothing is added, dropped, merged, or reclassified on the way through
 * (`contracts/model-server.md` point 3): every token this emits carries the kind the service gave
 * the characters it selects, and every character the service classified is selected by exactly one
 * token unless the protocol cannot express it.
 *
 * WHY THERE IS NO TOKEN TABLE HERE
 *
 * The protocol wants a legend: an ordered list of token type names, and an index into it per token.
 * The obvious way to supply one is to write the vocabulary down and map each of the service's kinds
 * onto a protocol name. That is the token table `contracts/model-server.md` forbids by name, and it
 * is forbidden for the usual reason: it would be right on the day it was written and quietly wrong
 * the first time the syntax layer named something new. So the legend is not written down. It starts
 * empty and is filled by the kinds the service actually returns, which makes the vocabulary the
 * service's in fact and not only in intent. `generation` moves whenever the legend grows, which is
 * the signal the wiring needs to advertise the legend again before the client can read the new
 * indices.
 *
 * WHAT THE PROTOCOL DOES REQUIRE
 *
 * Two things, and only two. Tokens arrive as deltas from the token before them, so they must be in
 * document order; the service is free to return its regions in any order and this file sorts them.
 * And a token's length is measured within one line, so a region that crosses a line ending is
 * emitted as one token per line it covers. That second one is a change of units and not a change of
 * answer: each piece carries the region's own kind, and the pieces together select the region's own
 * characters. A piece selecting no characters is not emitted, because there is no zero-character
 * span for a client to draw and omitting it changes what the client is told about nothing at all.
 *
 * WHAT THIS FILE DOES NOT DO
 *
 * It does not check that the regions cover the text. Totality is the service's guarantee, and a gap
 * in what it returns is its answer: filling one here would be this repository classifying
 * characters, which is precisely what it may not do. The suite asserts totality of the fixtures
 * rather than of this function, and says so where it does.
 */

import type { ClassifiedRegion } from '../language-service.js';
import type { LineIndex } from '../positions.js';

/** A character position far past the end of any line, so a lookup clamps to that line's end. */
const LINE_END = Number.MAX_SAFE_INTEGER;

/** The service reports no modifiers, so every token carries none. Inventing one would be a guess. */
const NO_MODIFIERS = 0;

/** The legend as the protocol asks for it at registration time. */
export interface ProtocolLegend {
  readonly tokenTypes: readonly string[];
  readonly tokenModifiers: readonly string[];
}

/** The protocol payload: five numbers per token, deltas from the token before. */
export interface SemanticTokensPayload {
  readonly data: readonly number[];
}

/**
 * The token types this server has advertised, in the order it advertised them.
 *
 * Empty until the service names a kind. Every entry arrived from a `ClassifiedRegion`, which is
 * what keeps the vocabulary the syntax layer's; a legend seeded by hand would be the table this
 * repository must not hold, so the constructor's argument exists for restoring a legend across a
 * restart and for nothing else.
 */
export class TokenLegend {
  readonly #types: string[];
  #generation: number;

  constructor(advertised: readonly string[] = []) {
    this.#types = [...advertised];
    this.#generation = 0;
  }

  get tokenTypes(): readonly string[] {
    return this.#types;
  }

  /** Always empty: the service reports no modifiers and this file may not invent any. */
  get tokenModifiers(): readonly string[] {
    return [];
  }

  get legend(): ProtocolLegend {
    return { tokenTypes: this.tokenTypes, tokenModifiers: this.tokenModifiers };
  }

  /** Moves when the legend grows, so the wiring knows the client's copy is behind. */
  get generation(): number {
    return this.#generation;
  }

  /** The index the client already holds for a kind, or nothing when it holds none. */
  indexOf(kind: string): number | undefined {
    const found = this.#types.indexOf(kind);
    return found < 0 ? undefined : found;
  }

  /** The index for a kind, admitting it to the legend the first time the service names it. */
  admit(kind: string): number {
    const known = this.indexOf(kind);
    if (known !== undefined) return known;
    this.#types.push(kind);
    this.#generation = this.#generation + 1;
    return this.#types.length - 1;
  }
}

/**
 * One region cut at the line endings it crosses, in the protocol's units.
 *
 * Exported because it is the whole of what "re-expressed, not reclassified" means here, and a test
 * that cannot see the pieces cannot tell the difference between this and a merge. Every piece
 * carries the region's own kind; pieces that select no characters are left out.
 */
export function linePieces(
  region: ClassifiedRegion,
  lines: LineIndex,
): readonly ClassifiedRegion[] {
  const from = lines.positionAt(region.start);
  const to = lines.positionAt(region.end);
  const pieces: ClassifiedRegion[] = [];
  for (let line = from.line; line <= to.line; line = line + 1) {
    const lineStart = lines.offsetAt({ line, character: 0 });
    const lineEnd = lines.offsetAt({ line, character: LINE_END });
    const start = Math.max(region.start, lineStart);
    const end = Math.min(region.end, lineEnd);
    if (end > start) pieces.push({ start, end, kind: region.kind });
  }
  return pieces;
}

/**
 * The service's regions as the protocol's delta encoding.
 *
 * `lines` is the document's text and the client's negotiated encoding, indexed once: every
 * conversion below runs through it, and no offset is measured here.
 */
export function semanticTokensFor(
  regions: readonly ClassifiedRegion[],
  lines: LineIndex,
  legend: TokenLegend,
): SemanticTokensPayload {
  // The one reorder the protocol requires. Sorting on the end as well keeps the output of two runs
  // over the same input identical, which a delta encoding makes worth having.
  const ordered = [...regions].sort(
    (left, right) => left.start - right.start || left.end - right.end,
  );

  const data: number[] = [];
  let lastLine = 0;
  let lastCharacter = 0;
  for (const region of ordered) {
    for (const piece of linePieces(region, lines)) {
      const from = lines.positionAt(piece.start);
      const to = lines.positionAt(piece.end);
      const length = to.character - from.character;
      if (length <= 0) continue;
      const deltaLine = from.line - lastLine;
      const deltaStart = deltaLine === 0 ? from.character - lastCharacter : from.character;
      data.push(deltaLine, deltaStart, length, legend.admit(piece.kind), NO_MODIFIERS);
      lastLine = from.line;
      lastCharacter = from.character;
    }
  }
  return { data };
}
