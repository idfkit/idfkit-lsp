/**
 * The language service's surface, taken from the package rather than described here.
 *
 * This file replaces a mirror. While `@idfkit/language` did not exist, this repository carried a
 * hand-written copy of its types so the server could be written and type-checked against something.
 * That copy said of itself that it should be deleted the day the package shipped, and this is that
 * deletion: every name below is re-exported or derived, and nothing is declared. A mirror kept past
 * its usefulness is a second declaration of somebody else's types, which is the drift Principle I
 * exists to prevent.
 *
 * WHY THE NAMES STILL COME THROUGH HERE
 *
 * Two reasons, and neither is a layer of its own. The handlers import a type from one place, so
 * where a type comes from is answered once rather than in six files. And the two packages behind
 * that one place are not interchangeable: the five answers come from `idfkit/language`, while the
 * schema, the syntax layer, the parsed model and a field's facts come from `idfkit` itself. Which
 * is which is a fact worth writing down once, and it is the only fact this file states.
 *
 * WHAT THIS COSTS
 *
 * Type checking now requires the library to be installed, because there is no longer a local
 * description to fall back on. That is the intended trade: a surface that cannot drift, in exchange
 * for a build that needs its dependency present.
 */

import type * as Language from 'idfkit/language';

/** The five answers, and the two positioning helpers that come with them. */
export type {
  CursorContext,
  CompletionOptions,
  CompletionResult,
  Offer,
  Explanation,
  ExplanationResult,
  Declaration,
  DeclarationResult,
  PositionedFinding,
} from 'idfkit/language';

/**
 * What the service takes and what it hands back that is not its own.
 *
 * A schema, a parsed model, a prose pool and the syntax layer all belong to the library, and the
 * service takes them as arguments. `Token` is renamed on the way through because a classified span
 * is what this repository calls it and `ClassifiedRegion` is the name every handler already uses.
 */
export type {
  Region,
  Token as ClassifiedRegion,
  SyntaxLayer,
  Statement,
  ParseDiagnostic,
  ValidationError,
  FieldDescription,
  ProsePool,
  DocsUrl,
  IdfDocument,
  Schema,
} from 'idfkit';

/**
 * The service as a whole, derived from the module rather than listed.
 *
 * `typeof` the module is exactly the six functions it exports, so a function added, removed or
 * re-signed upstream changes this type without anyone editing it. The previous mirror listed the
 * six by hand, which is the thing that could go stale.
 */
export type LanguageService = typeof Language;

/** Severity as a finding carries it, taken from the finding's own type. */
export type Severity = import('idfkit').ValidationError['severity'];

/** Either kind of finding the service positions. */
export type Finding = import('idfkit').ParseDiagnostic | import('idfkit').ValidationError;

/** The status word every cursor answer discriminates on. */
export type AnswerStatus = Language.CompletionResult['status'];
