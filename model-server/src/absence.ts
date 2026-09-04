/**
 * Three absences, kept three.
 *
 * FR-021 and `contracts/model-server.md` point 5 require "the schema permits
 * nothing here", "the schema constrains nothing here" and "no answer could be
 * produced" to reach the client distinguishably. The language service already
 * distinguishes them, so the only way this repository can lose the distinction
 * is by flattening it on the way through, which is what this module exists to
 * make awkward.
 *
 * An editor shown an empty list reads it as the first. Returning one for the
 * third would be this repository telling a lie on the service's behalf, which
 * Principle IV forbids by name.
 *
 * So: no function here turns an absence into a list, empty or otherwise, and
 * every mapping is exhaustive over the service's own status words. A status
 * this repository has never seen resolves to "cannot answer", never to
 * "permits nothing", because inventing certainty is the failure worth ruling
 * out and admitting ignorance is not.
 */

import type {
  CompletionResult,
  Declaration,
  DeclarationResult,
  Explanation,
  ExplanationResult,
  Offer,
} from './language-service.js';

/** The schema was consulted, and it permits nothing at this position. */
export interface PermitsNothing {
  readonly kind: 'permitsNothing';
  /**
   * Which way the service said so.
   *
   * `'empty'` is an answer that came back with nothing in it. `'notApplicable'`
   * is a position where the question does not arise, such as inside a comment.
   * Both are the schema declining to permit something, and neither is a
   * failure to consult it.
   */
  readonly reason: 'empty' | 'notApplicable';
}

/** The schema places no constraint here, so there is nothing to offer. */
export interface ConstrainsNothing {
  readonly kind: 'constrainsNothing';
}

/** No answer could be produced. This is not an empty list. */
export interface CannotAnswer {
  readonly kind: 'cannotAnswer';
  readonly reason: 'noSchema' | 'unknownType' | 'unrecognisedStatus';
  /** The type name the text wrote, when the schema does not define it. */
  readonly typeName: string | undefined;
}

/** The three, and only the three. */
export type Absence = PermitsNothing | ConstrainsNothing | CannotAnswer;

/** An answer the service did produce. */
export interface Answer<T> {
  readonly kind: 'answer';
  readonly value: T;
}

/** What a handler receives from a mapping below, and must match on in full. */
export type Outcome<T> = Answer<T> | Absence;

export function isAnswer<T>(outcome: Outcome<T>): outcome is Answer<T> {
  return outcome.kind === 'answer';
}

const CONSTRAINS_NOTHING: ConstrainsNothing = { kind: 'constrainsNothing' };

function permitsNothing(reason: PermitsNothing['reason']): PermitsNothing {
  return { kind: 'permitsNothing', reason };
}

function cannotAnswer(
  reason: CannotAnswer['reason'],
  typeName: string | undefined,
): CannotAnswer {
  return { kind: 'cannotAnswer', reason, typeName };
}

/**
 * The compile-time half of the guarantee.
 *
 * A status the mirrored surface does not carry fails to type-check here, which
 * is how a new one from a future release is noticed rather than absorbed. The
 * runtime half is the return: an unrecognised status is a reason no answer can
 * be given, so nothing downstream can mistake it for a schema that permitted
 * nothing.
 */
function unrecognised(status: never): CannotAnswer {
  return cannotAnswer('unrecognisedStatus', undefined);
}

/** What the schema permits at an offset, or which of the three absences applies. */
export function completionOutcome(result: CompletionResult): Outcome<readonly Offer[]> {
  switch (result.status) {
    case 'ok':
      return result.offers.length === 0
        ? permitsNothing('empty')
        : { kind: 'answer', value: result.offers };
    case 'unconstrained':
      return CONSTRAINS_NOTHING;
    case 'noSchema':
      return cannotAnswer('noSchema', undefined);
    case 'unknownType':
      return cannotAnswer('unknownType', result.typeName);
    case 'notApplicable':
      return permitsNothing('notApplicable');
    default:
      return unrecognised(result);
  }
}

/** What the schema says about the element under an offset, or which absence applies. */
export function explanationOutcome(result: ExplanationResult): Outcome<Explanation> {
  switch (result.status) {
    case 'ok':
      return { kind: 'answer', value: result.explanation };
    case 'unconstrained':
      return CONSTRAINS_NOTHING;
    case 'noSchema':
      return cannotAnswer('noSchema', undefined);
    case 'unknownType':
      return cannotAnswer('unknownType', result.typeName);
    case 'notApplicable':
      return permitsNothing('notApplicable');
    default:
      return unrecognised(result);
  }
}

/** Where the name under an offset is declared, or which absence applies. */
export function declarationOutcome(
  result: DeclarationResult,
): Outcome<readonly Declaration[]> {
  switch (result.status) {
    case 'ok':
      // Declared nowhere is the schema permitting no declaration here, not a
      // failure to look. The dangling-reference finding is what says why, and
      // a guess assembled here would contradict it.
      return result.declarations.length === 0
        ? permitsNothing('empty')
        : { kind: 'answer', value: result.declarations };
    case 'unconstrained':
      return CONSTRAINS_NOTHING;
    case 'noSchema':
      return cannotAnswer('noSchema', undefined);
    case 'unknownType':
      return cannotAnswer('unknownType', result.typeName);
    case 'notApplicable':
      return permitsNothing('notApplicable');
    default:
      return unrecognised(result);
  }
}
