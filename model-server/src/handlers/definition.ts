/**
 * Where the name under an offset is declared, translated.
 *
 * Every declaration the service reports is returned, in the order it reported them. Choosing one
 * would be this repository deciding which declaration a reader meant, and it has nothing to decide
 * that with: the service knows the reference graph and this file knows two offsets. A name declared
 * more than once is a real state of a real file, and showing a reader all of them is the only
 * answer that does not hide it.
 *
 * Nothing is returned where the service returns nothing. Where a name is declared nowhere, the
 * dangling-reference finding is what tells the reader why, and a guess assembled here would
 * contradict a finding the same server delivered a moment earlier.
 *
 * The declarations are in the text the service was given, which is the document the request named,
 * so the location's URI is that document's. This file resolves no other document and reads no file.
 */

import { declarationOutcome, isAnswer } from '../absence.js';

import type { Absence } from '../absence.js';
import type { DeclarationResult } from '../language-service.js';
import type { LineIndex } from '../positions.js';
import type { Location } from 'vscode-languageserver';

/** Every declaration, or the absence that stands in place of them. */
export type DefinitionAnswer =
  | { readonly kind: 'locations'; readonly locations: readonly Location[] }
  | { readonly kind: 'nothing'; readonly absence: Absence };

/**
 * The service's declarations as the protocol's locations.
 *
 * `lines` is the document's text and the client's negotiated encoding, indexed once; every range
 * is converted through it and none is measured here.
 */
export function definitionFor(
  result: DeclarationResult,
  uri: string,
  lines: LineIndex,
): DefinitionAnswer {
  const outcome = declarationOutcome(result);
  if (!isAnswer(outcome)) return { kind: 'nothing', absence: outcome };
  return {
    kind: 'locations',
    locations: outcome.value.map((declaration) => ({
      uri,
      range: lines.rangeOf(declaration.region),
    })),
  };
}
