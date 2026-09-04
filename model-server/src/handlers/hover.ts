/**
 * The schema's explanation of the element under an offset, translated.
 *
 * The rule this file exists to keep is the one that makes a hover feel haunted when it is broken:
 * on whitespace, on a separator, and inside a comment the service returns `notApplicable`, and the
 * honest answer there is nothing at all. Reaching for the nearest field would be this repository
 * answering a question the service declined, which is Principle IV's exact prohibition, and it is
 * the kind of wrong that looks right in a screenshot.
 *
 * So there is one path out of here that produces a hover, and it runs only on an explanation the
 * service produced. Every other status leaves as `nothing`, carrying which absence it was, because
 * the wiring is entitled to tell a reader why there is no explanation and cannot do that from an
 * empty hover.
 *
 * WHAT THE HOVER SAYS, AND WHAT IT CANNOT
 *
 * The names and the prose are the service's own strings, reproduced and never paraphrased: 005's
 * FR-022 forbids deriving text from a field's name, and there is nothing here that could. The
 * explanation's `field` and `docs` members are opaque to this repository on purpose, so they do not
 * appear: reading into a `FieldDescription` would mean knowing what a field description contains,
 * which is knowledge of the schema. When the service ships them in a shape a consumer may read,
 * this file gains a branch and not a table.
 */

import { MarkupKind } from 'vscode-languageserver';

import { explanationOutcome, isAnswer } from '../absence.js';

import type { Absence } from '../absence.js';
import type { Explanation, ExplanationResult } from '../language-service.js';
import type { LineIndex } from '../positions.js';
import type { Hover } from 'vscode-languageserver';

/** A hover, or the absence that stands in place of one. */
export type HoverAnswer =
  | { readonly kind: 'hover'; readonly hover: Hover }
  | { readonly kind: 'nothing'; readonly absence: Absence };

/** Markdown paragraphs are separated by a blank line, which is the only text this file writes. */
const PARAGRAPH = '\n\n';

/** A name shown as written, so markdown cannot re-punctuate somebody else's identifier. */
function asWritten(name: string): string {
  return `\`${name}\``;
}

/**
 * The explanation's own strings, in the order a reader wants them: what it is, then what it means.
 */
function markdownOf(explanation: Explanation): string {
  const paragraphs: string[] = [];
  paragraphs.push(asWritten(explanation.typeName));
  if (explanation.fieldName !== undefined) paragraphs.push(asWritten(explanation.fieldName));
  if (explanation.prose !== undefined) paragraphs.push(explanation.prose);
  return paragraphs.join(PARAGRAPH);
}

/**
 * The service's explanation as the protocol's hover, or nothing where the service said nothing.
 *
 * The range is the region the service said the explanation describes, converted through `lines`,
 * which is what the editor highlights while the hover is shown.
 */
export function hoverFor(result: ExplanationResult, lines: LineIndex): HoverAnswer {
  const outcome = explanationOutcome(result);
  if (!isAnswer(outcome)) return { kind: 'nothing', absence: outcome };
  const explanation = outcome.value;
  return {
    kind: 'hover',
    hover: {
      contents: { kind: MarkupKind.Markdown, value: markdownOf(explanation) },
      range: lines.rangeOf(explanation.region),
    },
  };
}
