/**
 * Findings, translated (T043, T047).
 *
 * What these assert is mostly a set of absences: that nothing was reworded, that nothing was
 * re-graded, that nothing was invented, and that a finding from reading the text and a finding from
 * validating the model are treated identically because the handler cannot tell them apart. Every
 * finding here is a hand-written stand-in for what `@idfkit/language` would produce, which is what
 * lets these run today and is also the right shape: a translation is completely tested by a fake
 * input, and a handler that needed a real service would be doing more than translating.
 */

import { describe, expect, it } from 'vitest';

import {
  diagnosticsDelivery,
  diagnosticsFor,
  fullDocumentReport,
  publishDiagnosticsFor,
} from '../src/handlers/diagnostics.js';
import { LineIndex } from '../src/positions.js';

import type {
  Finding,
  ParseDiagnostic,
  PositionedFinding,
  ValidationError,
} from '../src/language-service.js';
import type { ClientCapabilities } from 'vscode-languageserver';

const TEXT = 'Zone,\n  Office,\n  bad;\n';
const lines = () => new LineIndex(TEXT, 'utf-16');

/** A finding from reading the text. Carries no severity, because the shape carries none. */
const FROM_READING: PositionedFinding<ParseDiagnostic> = {
  message: 'expected a terminator before the end of the file',
  line: 3,
  code: 'ParseError',
  region: { start: 0, end: 4 },
  precision: 'statement',
};

/** A finding from validating the model. Carries the severity the validator gave it. */
const FROM_VALIDATING: PositionedFinding<ValidationError> = {
  severity: 'warning',
  objType: 'Zone',
  objName: 'Office',
  field: 'ceiling_height',
  message: 'value is below the schema minimum',
  code: 'V-RANGE-2',
  region: { start: 18, end: 21 },
  precision: 'field',
};

const BOTH: readonly PositionedFinding<Finding>[] = [FROM_READING, FROM_VALIDATING];

describe('message, severity, and code pass through unchanged', () => {
  it('reproduces every message exactly, in the order the service gave them', () => {
    const out = diagnosticsFor(BOTH, lines());
    expect(out.map((one) => one.message)).toEqual([FROM_READING.message, FROM_VALIDATING.message]);
  });

  it('reproduces every code exactly', () => {
    const out = diagnosticsFor(BOTH, lines());
    expect(out.map((one) => one.code)).toEqual([FROM_READING.code, FROM_VALIDATING.code]);
  });

  it('carries a severity the finding stated', () => {
    // 2 is the protocol's warning, which is the word the validator used and nothing more.
    expect(diagnosticsFor([FROM_VALIDATING], lines())[0]?.severity).toBe(2);
  });

  it('carries no severity where the finding stated none', () => {
    const [only] = diagnosticsFor([FROM_READING], lines());
    expect(only?.severity).toBeUndefined();
    expect(Object.hasOwn(only ?? {}, 'severity')).toBe(false);
  });

  it('does not substitute text for a finding whose message is empty', () => {
    const silent: PositionedFinding<ParseDiagnostic> = { ...FROM_READING, message: '' };
    expect(diagnosticsFor([silent], lines())[0]?.message).toBe('');
  });

  it('carries no code where the finding stated none', () => {
    const uncoded: PositionedFinding<ParseDiagnostic> = {
      message: FROM_READING.message,
      line: FROM_READING.line,
      region: FROM_READING.region,
      precision: FROM_READING.precision,
    };
    expect(Object.hasOwn(diagnosticsFor([uncoded], lines())[0] ?? {}, 'code')).toBe(false);
  });

  it('translates the region and changes nothing else about it', () => {
    const index = lines();
    const out = diagnosticsFor(BOTH, index);
    expect(out[0]?.range).toEqual(index.rangeOf(FROM_READING.region));
    expect(out[1]?.range).toEqual(index.rangeOf(FROM_VALIDATING.region));
    // The range selects the characters the service selected, which is the only claim worth making.
    expect(TEXT.slice(FROM_VALIDATING.region.start, FROM_VALIDATING.region.end)).toBe('bad');
  });

  it('passes the service own precision through for a consumer to draw on', () => {
    const out = diagnosticsFor(BOTH, lines());
    expect(out.map((one) => one.data)).toEqual([
      { precision: 'statement' },
      { precision: 'field' },
    ]);
  });
});

describe('reading and validating arrive on the same terms', () => {
  it('returns one list, in the service order, with neither kind grouped or moved', () => {
    const reversed = [FROM_VALIDATING, FROM_READING];
    expect(diagnosticsFor(reversed, lines()).map((one) => one.message)).toEqual([
      FROM_VALIDATING.message,
      FROM_READING.message,
    ]);
  });

  it('gives both kinds the same treatment of their region', () => {
    const index = lines();
    const shared = { region: { start: 8, end: 14 }, precision: 'field' } as const;
    const read: PositionedFinding<ParseDiagnostic> = { ...FROM_READING, ...shared };
    const validated: PositionedFinding<ValidationError> = { ...FROM_VALIDATING, ...shared };
    expect(diagnosticsFor([read], index)[0]?.range).toEqual(
      diagnosticsFor([validated], index)[0]?.range,
    );
  });
});

describe('no finding is produced here', () => {
  it('answers an empty list with an empty list', () => {
    expect(diagnosticsFor([], lines())).toEqual([]);
    expect(fullDocumentReport([], lines()).items).toEqual([]);
    expect(publishDiagnosticsFor('file:///a.idf', 1, [], lines()).diagnostics).toEqual([]);
  });

  it('emits exactly one diagnostic per finding, for every length of input', () => {
    const index = lines();
    for (let count = 0; count <= 12; count = count + 1) {
      const findings: PositionedFinding<Finding>[] = [];
      for (let made = 0; made < count; made = made + 1) {
        findings.push({ ...FROM_READING, message: `finding ${made}` });
      }
      const out = diagnosticsFor(findings, index);
      expect(out.length).toBe(count);
      expect(out.map((one) => one.message)).toEqual(findings.map((one) => one.message));
    }
  });

  it('holds no text of its own that could become a diagnostic', () => {
    // Every message and code that leaves the handler is identical to one that entered it. A
    // diagnostic constructed anywhere else in the module would have to carry a message from
    // somewhere, and there is nowhere here for one to come from.
    const strange: PositionedFinding<ValidationError> = {
      ...FROM_VALIDATING,
      message: '  not a sentence \u{1F600}',
      code: '',
    };
    const [only] = diagnosticsFor([strange], lines());
    expect(only?.message).toBe(strange.message);
    expect(only?.code).toBe('');
  });

  it('sets no source, because the handler is not who produced the finding', () => {
    expect(Object.hasOwn(diagnosticsFor(BOTH, lines())[0] ?? {}, 'source')).toBe(false);
  });
});

describe('on request where the client can request, published only where it cannot', () => {
  const canRequest: ClientCapabilities = {
    textDocument: { diagnostic: { dynamicRegistration: false, relatedDocumentSupport: false } },
  };
  const cannotRequest: ClientCapabilities = { textDocument: {} };

  it('serves on request for a client that advertises the pull request', () => {
    expect(diagnosticsDelivery(canRequest)).toBe('onRequest');
  });

  it('publishes on change for a client that does not', () => {
    expect(diagnosticsDelivery(cannotRequest)).toBe('onChange');
    expect(diagnosticsDelivery({})).toBe('onChange');
    expect(diagnosticsDelivery(undefined)).toBe('onChange');
  });

  it('reports a full document report, which is the whole answer and not a delta', () => {
    const report = fullDocumentReport(BOTH, lines());
    expect(report.kind).toBe('full');
    expect(report.items.length).toBe(BOTH.length);
    expect(Object.hasOwn(report, 'resultId')).toBe(false);
  });

  it('carries a result identifier only when it was given one', () => {
    expect(fullDocumentReport(BOTH, lines(), 'v7').resultId).toBe('v7');
  });

  it('publishes against the version the answer was computed on', () => {
    const params = publishDiagnosticsFor('file:///a.idf', 42, BOTH, lines());
    expect(params.uri).toBe('file:///a.idf');
    expect(params.version).toBe(42);
    expect(params.diagnostics.map((one) => one.message)).toEqual(BOTH.map((one) => one.message));
  });
});
