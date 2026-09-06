/**
 * What the schema permits at an offset, translated.
 *
 * The point of this file is what it does not contain. There is no list of candidates here, so there
 * is nothing to fall back to when the service declines to answer: every label that reaches a client
 * came out of an `Offer` the service produced, and the module holds no string a user could mistake
 * for one. That is Principle IV made structural rather than promised.
 *
 * THREE ABSENCES, STILL THREE
 *
 * `absence.ts` already separates "the schema permits nothing here", "the schema constrains nothing
 * here", and "no answer could be produced". This file must not put them back together, and the
 * protocol makes that easy to do by accident, because a completion list has one shape and an empty
 * one says only "nothing to offer".
 *
 * So the two schema answers become an empty list marked complete, which is what an editor should
 * show when the schema was consulted and had nothing to add, and each carries which of the two it
 * was so the wiring can say so. "No answer could be produced" is not a list at all: it leaves here
 * as `cannotAnswer`, and the wiring reports it as an error or as an incomplete result carrying the
 * reason. An empty complete list there would tell the user the schema permits nothing, which is a
 * different claim and a false one.
 *
 * THE REPLACED SPAN IS THE SERVICE'S
 *
 * Each offer carries the region it would replace (unification 005, FR-048), and this file uses that
 * region and never measures a word. The editor's default word rules break on this format in both
 * directions: a type name contains a colon and reads as two words, a value contains spaces and
 * reads as three. Deriving the span here would be wrong on most real completions, and it would be
 * the grammar knowledge this repository may not hold.
 */

import { CompletionItemKind, MarkupKind } from 'vscode-languageserver';

import { completionOutcome, isAnswer } from '../absence.js';

import type { CannotAnswer, ConstrainsNothing, PermitsNothing } from '../absence.js';
import type { CompletionResult, Offer } from '../language-service.js';
import type { LineIndex } from '../positions.js';
import type { CompletionItem, CompletionList } from 'vscode-languageserver';

/**
 * The word shown against an offer the schema marks required.
 *
 * A rendering of the service's own boolean, and the only text in this file a user ever sees. It
 * says nothing about the model that the service did not say first.
 */
const REQUIRED = 'required';

/** A completion answer, with the absences kept apart. */
export type CompletionAnswer =
  | {
      readonly kind: 'list';
      readonly list: CompletionList;
      /** Which schema answer an empty list stands for. Undefined when the list has items. */
      readonly absence: PermitsNothing | ConstrainsNothing | undefined;
    }
  | {
      readonly kind: 'cannotAnswer';
      /** Never a list. The wiring reports the reason rather than showing an empty one. */
      readonly absence: CannotAnswer;
    };

/** The protocol's item kind for an offer's own kind. Three answers, and no fourth invented. */
function itemKindOf(offer: Offer): CompletionItemKind | undefined {
  switch (offer.kind) {
    case 'objectType':
      return CompletionItemKind.Class;
    case 'enumValue':
      return CompletionItemKind.EnumMember;
    case 'referenceTarget':
      return CompletionItemKind.Reference;
    default:
      return undefined;
  }
}

/**
 * One offer as one item.
 *
 * The prose travels as plain text because it is the schema's own wording and markdown would let a
 * stray character in it change how it reads.
 */
function itemOf(offer: Offer, lines: LineIndex): CompletionItem {
  const kind = itemKindOf(offer);
  return {
    label: offer.value,
    ...(kind === undefined ? {} : { kind }),
    ...(offer.required === true ? { detail: REQUIRED } : {}),
    ...(offer.prose === undefined
      ? {}
      : { documentation: { kind: MarkupKind.PlainText, value: offer.prose } }),
    textEdit: { range: lines.rangeOf(offer.replaces), newText: offer.value },
  };
}

/** A list the client should not ask about again. Empty or not, it is the whole answer. */
function complete(items: CompletionItem[]): CompletionList {
  return { isIncomplete: false, items };
}

/**
 * The service's answer as the protocol's.
 *
 * `lines` is the document's text and the client's negotiated encoding, indexed once; every range
 * below is converted through it and none is measured here.
 */
export function completionFor(result: CompletionResult, lines: LineIndex): CompletionAnswer {
  const outcome = completionOutcome(result);
  if (isAnswer(outcome)) {
    return {
      kind: 'list',
      list: complete(outcome.value.map((offer) => itemOf(offer, lines))),
      absence: undefined,
    };
  }
  if (outcome.kind === 'cannotAnswer') {
    return { kind: 'cannotAnswer', absence: outcome };
  }
  return { kind: 'list', list: complete([]), absence: outcome };
}
