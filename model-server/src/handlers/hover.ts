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
 * FR-022 forbids deriving text from a field's name, and there is nothing here that could.
 *
 * `field` and `docs` were opaque while this repository carried a mirror of the service's types,
 * which described both as bare objects. They are not opaque any more: `@idfkit/language` ships and
 * `FieldDescription` and `DocsUrl` are published types with named members. Reading `units` off one
 * is reading a library's own type, which is the same thing the source server's analyzer does with
 * the first language's API and which the constitution retains by name as shape rather than schema.
 * What would still be forbidden is a table here saying which fields a type has, or what any
 * particular field means. Nothing below knows the name of a single object type or field: it reads
 * members off whatever description it was handed and reports the ones that are present.
 *
 * The absences are reported by omission rather than by writing "unknown". A field with no units
 * has no units, and a line saying so would be this file talking about itself instead of about the
 * field.
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

/** The separator between facts on one line, which is the only punctuation this file writes. */
const BETWEEN = ' · ';

/**
 * A value as the schema stated it, shown as written.
 *
 * The schema's values are strings and numbers, and a number is rendered by the runtime's own rule
 * rather than formatted here: choosing a precision would be this file deciding what a value means.
 */
function asValue(value: string | number | boolean): string {
  return `\`${String(value)}\``;
}

/**
 * The field's own facts, each reported only where the description carries it.
 *
 * Nothing here is derived. Every line is a member read off the description the service handed over,
 * and a member that is undefined produces no line at all.
 */
function factsOf(field: NonNullable<Explanation['field']>): string[] {
  const facts: string[] = [];
  if (field.fieldType !== undefined) facts.push(field.fieldType);
  facts.push(field.required ? 'required' : 'optional');
  if (field.units !== undefined) facts.push(field.units);
  if (field.default !== undefined) facts.push(`default ${asValue(field.default)}`);

  const lines = [facts.join(BETWEEN)];

  // The bounds, on their own line, and only the ends that exist. A field bounded below and not
  // above is a real shape, so the two ends are reported separately rather than as a range.
  const bounds: string[] = [];
  if (field.minimum !== undefined) bounds.push(`min ${asValue(field.minimum)}`);
  if (field.maximum !== undefined) bounds.push(`max ${asValue(field.maximum)}`);
  if (bounds.length > 0) lines.push(bounds.join(BETWEEN));

  // The permitted values, as the schema lists them and in its order. Not sorted and not truncated:
  // both would be this file editing the schema's answer.
  if (field.enumValues !== undefined && field.enumValues.length > 0) {
    lines.push(field.enumValues.map(asValue).join(', '));
  }

  // What a reference points into, which is the schema's own list of list names.
  if (field.isReference && field.objectList !== undefined && field.objectList.length > 0) {
    lines.push(`refers to ${field.objectList.map(asWritten).join(', ')}`);
  }

  return lines;
}

/**
 * The explanation, in the order a reader wants it: what it is, what it means, then where to read
 * more.
 */
function markdownOf(explanation: Explanation): string {
  const paragraphs: string[] = [];

  const heading =
    explanation.fieldName === undefined
      ? asWritten(explanation.typeName)
      : `${asWritten(explanation.typeName)}${BETWEEN}${asWritten(explanation.fieldName)}`;
  paragraphs.push(heading);

  // The schema's own sentence, when the caller loaded a pool for it to be drawn from. Absent
  // rather than substituted: there is nothing here that could write one.
  if (explanation.prose !== undefined) paragraphs.push(explanation.prose);

  if (explanation.field !== undefined) paragraphs.push(factsOf(explanation.field).join('\n\n'));

  // The manual, under the label the library gave it. The address is the library's and is not
  // assembled here.
  const docs = explanation.docs;
  if (docs !== undefined) paragraphs.push(`[${docs.label}](${docs.url})`);

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
