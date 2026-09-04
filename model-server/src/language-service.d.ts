/**
 * The contracted surface of `@idfkit/language`, mirrored so this server can be
 * written and type-checked while the package does not exist.
 *
 * MIRRORS: idfkit-unification/specs/005-idf-language-service/contracts/language-service.md,
 * with the entity shapes from that feature's data-model.md and the positioning
 * rules from contracts/positioning.md. Reconciled here through
 * specs/001-two-server-editor-support/contracts/language-service-expected.md,
 * which is the one document to check against the naming register when 005 lands.
 *
 * DELETE THIS FILE the day `@idfkit/language` ships. `idfkit/language` resolves
 * to the package's own `language.d.ts`, which is the plain re-export of the
 * package's real surface, and that surface is the truth. A mirror kept past its
 * usefulness is a second declaration of somebody else's types, which is the
 * shape of the drift the constitution's first principle exists to prevent.
 *
 * Nothing here describes IDF. Every type this repository would have to
 * understand the format to write is left opaque on purpose: a schema, a
 * document, a prose pool, a syntax layer and a statement are passed along and
 * never read into. The one vocabulary that does appear is a finding's severity,
 * which is a finding's own property and not a fact about the format.
 */

/**
 * A schema, as the service takes one.
 *
 * Opaque. This repository resolves one and hands it over; it never reads inside
 * one, and a type describing what is inside would be the schema table
 * Principle I forbids. The same goes for every alias below it.
 */
export type Schema = object;

/** A parsed model, supplying reference candidates and declarations. Opaque. */
export type IdfDocument = object;

/** The caller's loaded prose, which stays the caller's to load. Opaque. */
export type ProsePool = object;

/** The tokenised whole of one text, from `@idfkit/core`. Opaque. */
export type SyntaxLayer = object;

/** One statement in the text. Opaque; regions are what this repository reads. */
export type Statement = object;

/** A field's facts, exactly as `describeObjectType` returns them. Opaque. */
export type FieldDescription = object;

/** Where the manual documents a type, from `docsUrlForObject`. Opaque. */
export type DocsUrl = object;

/**
 * A half-open span of the text, in UTF-16 code units.
 *
 * The service states the unit; converting it to the unit the client negotiated
 * is this repository's job and happens in `positions.ts` alone.
 */
export interface Region {
  /** Offset of the first character, into the source string. */
  readonly start: number;
  /** Offset one past the last character. */
  readonly end: number;
}

/**
 * One classified span, from `classify` in `@idfkit/core`.
 *
 * `kind` is a string rather than a union on purpose. The vocabulary belongs to
 * the syntax layer, and a copy of it here would be the token table Principle I
 * forbids. The semantic tokens handler maps whatever it receives onto the
 * protocol's legend and reports what it cannot map.
 */
export interface ClassifiedRegion extends Region {
  readonly kind: string;
}

/** Where an offset falls, and in what. */
export interface CursorContext {
  readonly statement: Statement;
  readonly at: 'typeName' | 'field' | 'comment' | 'betweenStatements';
  /** Positional index of the field, when `at` is `'field'`. */
  readonly fieldIndex: number | undefined;
  /** The canonical type name, when the schema defines it. */
  readonly typeName: string | undefined;
  /** The schema field name, when the type is known and the index is in range. */
  readonly fieldName: string | undefined;
}

/** Something the schema permits at a position. */
export interface Offer {
  /** The text to insert. */
  readonly value: string;
  /**
   * The span this offer would replace.
   *
   * Carried by the service because working it out needs the format's rules and
   * not the editor's. This repository translates it and never derives it.
   */
  readonly replaces: Region;
  readonly kind: 'objectType' | 'enumValue' | 'referenceTarget';
  /** Whether the schema marks the field required. Undefined for object types. */
  readonly required: boolean | undefined;
  /** The schema's own prose, when the caller supplied the pool. */
  readonly prose: string | undefined;
}

/** What the schema says about the element under an offset. */
export interface Explanation {
  /** The span the explanation describes, for a consumer to highlight. */
  readonly region: Region;
  readonly of: 'objectType' | 'field';
  readonly typeName: string;
  readonly fieldName: string | undefined;
  /** The schema's own prose. Undefined when there is none, never derived. */
  readonly prose: string | undefined;
  readonly field: FieldDescription | undefined;
  readonly docs: DocsUrl | undefined;
}

/** Where a name is declared. */
export interface Declaration {
  readonly region: Region;
  readonly typeName: string;
}

/** Severity as a finding carries it. The service invents none of these. */
export type Severity = 'error' | 'warning' | 'info';

/**
 * A parse finding, in the members that cross into the protocol.
 *
 * `@idfkit/core` carries more on its own type. Message, code and severity are
 * the ones `contracts/model-server.md` requires to pass through unchanged.
 */
export interface ParseDiagnostic {
  readonly message: string;
  readonly line: number;
  readonly code?: string | undefined;
  readonly column?: number | undefined;
  readonly typeName?: string | undefined;
  readonly objectName?: string | undefined;
}

/** A validation finding, in the members that cross into the protocol. */
export interface ValidationError {
  readonly severity: Severity;
  readonly objType: string;
  readonly objName: string;
  readonly field: string | undefined;
  readonly message: string;
  readonly code: string;
}

/** Either kind of finding the service positions. */
export type Finding = ParseDiagnostic | ValidationError;

/**
 * A finding with the span it concerns attached. Not a new finding.
 *
 * `precision` records whether the span selects the offending field or falls
 * back to the whole statement, so a consumer can draw the two differently and a
 * test can assert the fallback was not taken where it should not have been.
 */
export type PositionedFinding<F> = F & {
  readonly region: Region;
  readonly precision: 'field' | 'statement';
};

/** Which candidates and prose a completion may draw on. */
export interface CompletionOptions {
  /** Supplies candidate names for reference fields. Omit and none are offered. */
  readonly document?: IdfDocument | undefined;
  /** Supplies prose for the offers. Omit and offers carry none. */
  readonly prose?: ProsePool | undefined;
}

/**
 * The statuses every cursor answer shares.
 *
 * The point of the union is that "the schema permits nothing here", "the schema
 * constrains nothing here" and "no schema could be consulted" are three states
 * and not one empty array. `absence.ts` is what keeps them three on the way to
 * the client.
 */
export type CompletionResult =
  | { readonly status: 'ok'; readonly offers: readonly Offer[] }
  | { readonly status: 'unconstrained' }
  | { readonly status: 'noSchema' }
  | { readonly status: 'unknownType'; readonly typeName: string }
  | { readonly status: 'notApplicable' };

/**
 * NOT YET FIXED BY 005: the member that carries the payload on `'ok'`.
 * `CompletionResult` names its `offers`; the contract says the other two answers
 * "carry the same discriminated shape" without naming their payloads. These two
 * names are this mirror's reading and are the first thing to check against the
 * package when it ships.
 */
export type ExplanationResult =
  | { readonly status: 'ok'; readonly explanation: Explanation }
  | { readonly status: 'unconstrained' }
  | { readonly status: 'noSchema' }
  | { readonly status: 'unknownType'; readonly typeName: string }
  | { readonly status: 'notApplicable' };

export type DeclarationResult =
  | { readonly status: 'ok'; readonly declarations: readonly Declaration[] }
  | { readonly status: 'unconstrained' }
  | { readonly status: 'noSchema' }
  | { readonly status: 'unknownType'; readonly typeName: string }
  | { readonly status: 'notApplicable' };

/** The status word every answer above discriminates on. */
export type AnswerStatus = CompletionResult['status'];

/**
 * The six functions this repository calls.
 *
 * Every one is synchronous and performs no input or output, so no handler ever
 * awaits an answer. `scanIdf` and `classify` are deliberately absent: they come
 * from `@idfkit/core` at the `idfkit` subpath, and naming them here would give a
 * reader two names for one function.
 */
export interface LanguageService {
  contextAt(text: string, offset: number, schema?: Schema): CursorContext;
  completionsAt(
    text: string,
    offset: number,
    schema: Schema,
    options?: CompletionOptions,
  ): CompletionResult;
  explainAt(text: string, offset: number, schema: Schema, prose?: ProsePool): ExplanationResult;
  declarationAt(
    text: string,
    offset: number,
    schema: Schema,
    document: IdfDocument,
  ): DeclarationResult;
  findingsIn(text: string, schema: Schema): readonly PositionedFinding<Finding>[];
  position<F>(
    findings: readonly F[],
    layer: SyntaxLayer,
    schema: Schema,
  ): readonly PositionedFinding<F>[];
}
