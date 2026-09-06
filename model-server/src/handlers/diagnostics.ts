/**
 * Findings, delivered on request where the client can request and published on change where it
 * cannot.
 *
 * Every function here is a translation and none of them is a judgement. Message, severity, and code
 * are the service's, carried across untouched (`contracts/model-server.md` point 4, FR-020); the
 * range is the service's own region, converted into the client's units by `positions.ts`; and the
 * count of what comes out equals the count of what went in. There is no path through this file that
 * builds a finding, because there is nothing in this file to build one from: no message text, no
 * default severity, no rule that would produce one.
 *
 * TWO OMISSIONS THAT ARE DELIBERATE
 *
 * A parse finding carries no severity. The protocol lets a diagnostic omit one and leaves the
 * choice to the client, so the field is omitted rather than filled with a plausible default. A
 * default chosen here would be this repository deciding how serious somebody else's finding is.
 *
 * No `source` is set. It names who produced a finding, and the honest answer is the language
 * service rather than this server, which is not a string this file is in a position to write.
 *
 * ON REQUEST, NOT PUSHED
 *
 * research.md R11: serving on request needs no debounce, no scheduler, and no cache invalidation
 * policy, and every one of those would be machinery this repository owned and the service did not.
 * `diagnosticsDelivery` reads the client's own advertisement and nothing else, so the fallback runs
 * only for a client that cannot ask.
 */

import { DiagnosticSeverity, DocumentDiagnosticReportKind } from 'vscode-languageserver';

import type { Finding, PositionedFinding } from '../language-service.js';
import type { LineIndex } from '../positions.js';
import type {
  ClientCapabilities,
  Diagnostic,
  FullDocumentDiagnosticReport,
  PublishDiagnosticsParams,
} from 'vscode-languageserver';

/** Which way findings reach this client. */
export type DiagnosticsDelivery = 'onRequest' | 'onChange';

/**
 * How this client takes findings.
 *
 * A client that advertises the pull request takes them on request; one that does not gets them
 * published. Read from the client's advertisement rather than configured, so the two cannot drift.
 */
export function diagnosticsDelivery(
  capabilities: ClientCapabilities | undefined,
): DiagnosticsDelivery {
  return capabilities?.textDocument?.diagnostic === undefined ? 'onChange' : 'onRequest';
}

/**
 * The protocol's severity for a finding that carries one, and nothing for a finding that does not.
 *
 * The three words are the finding's own property, which the mirrored surface notes is a fact about
 * the finding rather than about the format. An unrecognised word yields nothing, on the same
 * reasoning as `absence.ts`: admitting ignorance is safe and inventing certainty is not.
 */
function severityOf(finding: Finding): DiagnosticSeverity | undefined {
  if (!('severity' in finding)) return undefined;
  switch (finding.severity) {
    case 'error':
      return DiagnosticSeverity.Error;
    case 'warning':
      return DiagnosticSeverity.Warning;
    case 'info':
      return DiagnosticSeverity.Information;
    default:
      return undefined;
  }
}

/** The finding's own code, when it carries one. Never derived from anything else. */
function codeOf(finding: Finding): string | undefined {
  return 'code' in finding ? finding.code : undefined;
}

/**
 * One finding as one diagnostic.
 *
 * `precision` rides along in `data` because it is the service's own record of whether the region
 * selects the offending value or falls back to the whole statement, and a client that wants to draw
 * the two differently has no other way to tell. It is passed through, not computed.
 */
function diagnosticOf(finding: PositionedFinding<Finding>, lines: LineIndex): Diagnostic {
  const severity = severityOf(finding);
  const code = codeOf(finding);
  return {
    range: lines.rangeOf(finding.region),
    message: finding.message,
    ...(severity === undefined ? {} : { severity }),
    ...(code === undefined ? {} : { code }),
    data: { precision: finding.precision },
  };
}

/**
 * Every finding the service positioned, in the order it positioned them.
 *
 * Findings from reading the text and findings from validating the model arrive on the same terms:
 * one list, one translation, no grouping and no reordering. Which of the two a finding came from is
 * the service's business, and this file cannot tell them apart on purpose.
 */
export function diagnosticsFor(
  findings: readonly PositionedFinding<Finding>[],
  lines: LineIndex,
): Diagnostic[] {
  return findings.map((finding) => diagnosticOf(finding, lines));
}

/** The answer to `textDocument/diagnostic`, which is the path a modern client takes. */
export function fullDocumentReport(
  findings: readonly PositionedFinding<Finding>[],
  lines: LineIndex,
  resultId?: string,
): FullDocumentDiagnosticReport {
  return {
    kind: DocumentDiagnosticReportKind.Full,
    ...(resultId === undefined ? {} : { resultId }),
    items: diagnosticsFor(findings, lines),
  };
}

/**
 * The fallback for a client that cannot request, carrying the version the answer was computed
 * against so a client can discard one the editor has since superseded.
 */
export function publishDiagnosticsFor(
  uri: string,
  version: number,
  findings: readonly PositionedFinding<Finding>[],
  lines: LineIndex,
): PublishDiagnosticsParams {
  return { uri, version, diagnostics: diagnosticsFor(findings, lines) };
}
