/**
 * The single declared exception to Constitution Principle I.
 *
 * Principle I forbids this repository from computing over model text: no schema table, no grammar
 * pattern, no arithmetic that derives meaning from an offset. This module is the one place the rule
 * is lifted, and it is lifted for a reason that cannot be designed away. The Language Server
 * Protocol asks for a line and a character measured in a negotiated encoding. The idfkit language
 * service states its regions as absolute offsets into the text, and feature 005 of the unification
 * forbids the service from naming a protocol's types, precisely so that a second protocol would not
 * force a second unit into the library. The conversion therefore lands on this side by
 * construction, and confining it to one named module is what keeps Principle I checkable rather
 * than aspirational: `tools/check_knowledge.py` exempts this file by name and no other.
 *
 * What that exemption buys is narrow. This module knows about code units, code points, and the
 * three ways a line can end. It knows nothing about IDF: no object type, no field name, no token
 * kind, and none may appear here. It converts between text encodings, never between meanings.
 *
 * Incoming offsets are UTF-16 code units, because that is what a JavaScript string index is and
 * what the service measures in (unification 005, contracts/positioning.md).
 */

/** The position encodings the protocol can negotiate. */
export type PositionEncoding = 'utf-8' | 'utf-16' | 'utf-32';

/** A protocol position: a zero-based line and a character in the negotiated encoding. */
export interface ProtocolPosition {
  readonly line: number;
  readonly character: number;
}

/** A protocol range, structurally the `Range` the protocol carries. */
export interface ProtocolRange {
  readonly start: ProtocolPosition;
  readonly end: ProtocolPosition;
}

/** A region as the language service states it: absolute UTF-16 offsets into the text. */
export interface ServiceRegion {
  readonly start: number;
  readonly end: number;
}

const CR = 13;
const LF = 10;

/** How many UTF-8 bytes encode one code point. */
function utf8Width(codePoint: number): number {
  if (codePoint < 0x80) return 1;
  if (codePoint < 0x800) return 2;
  if (codePoint < 0x10000) return 3;
  return 4;
}

/** Width of one code point in the negotiated encoding. */
function unitWidth(codePoint: number, encoding: PositionEncoding): number {
  switch (encoding) {
    case 'utf-8':
      return utf8Width(codePoint);
    case 'utf-32':
      return 1;
    case 'utf-16':
      return codePoint > 0xffff ? 2 : 1;
  }
}

/** Measure a line prefix in the negotiated encoding. */
function measure(prefix: string, encoding: PositionEncoding): number {
  if (encoding === 'utf-16') return prefix.length;
  let units = 0;
  for (const character of prefix) {
    units += unitWidth(character.codePointAt(0) ?? 0, encoding);
  }
  return units;
}

/**
 * The inverse of `measure`: the UTF-16 offset within `line` at which `target` units have been
 * consumed. A target landing inside a character resolves to that character's start, which is what
 * keeps a surrogate pair from being split.
 */
function offsetWithinLine(line: string, target: number, encoding: PositionEncoding): number {
  if (target <= 0) return 0;
  let units = 0;
  let offset = 0;
  while (offset < line.length) {
    const codePoint = line.codePointAt(offset) ?? 0;
    const step = codePoint > 0xffff ? 2 : 1;
    const cost = unitWidth(codePoint, encoding);
    if (units + cost > target) return offset;
    units += cost;
    offset += step;
  }
  return line.length;
}

/**
 * Line offsets for one document text, computed once so that a conversion is a binary search rather
 * than a scan. Construct one per document version and reuse it for every position it needs.
 */
export class LineIndex {
  private readonly text: string;
  private readonly encoding: PositionEncoding;
  /** Offset of the first character of each line. Never empty. */
  private readonly lineStarts: readonly number[];
  /** Offset just past each line's content, excluding its terminator. Same length as lineStarts. */
  private readonly lineEnds: readonly number[];

  constructor(text: string, encoding: PositionEncoding = 'utf-16') {
    this.text = text;
    this.encoding = encoding;

    const starts: number[] = [0];
    const ends: number[] = [];
    let offset = 0;
    while (offset < text.length) {
      const unit = text.charCodeAt(offset);
      if (unit === CR) {
        ends.push(offset);
        // A CRLF is one line ending, not two.
        offset += text.charCodeAt(offset + 1) === LF ? 2 : 1;
        starts.push(offset);
      } else if (unit === LF) {
        ends.push(offset);
        offset += 1;
        starts.push(offset);
      } else {
        offset += 1;
      }
    }
    ends.push(text.length);

    this.lineStarts = starts;
    this.lineEnds = ends;
  }

  /** How many lines the text has. A text ending in a terminator has an empty final line. */
  get lineCount(): number {
    return this.lineStarts.length;
  }

  /**
   * The protocol position of a UTF-16 offset, in the negotiated encoding. An offset outside the
   * text clamps to the nearest end, an offset inside a line terminator clamps to that line's end,
   * and an offset between the halves of an astral character resolves to the character's start.
   */
  positionAt(offset: number): ProtocolPosition {
    const clamped = this.clampOffset(offset);
    const line = this.lineOf(clamped);
    const start = this.lineStarts[line] ?? 0;
    const end = this.lineEnds[line] ?? this.text.length;
    const within = Math.min(clamped, end);
    return { line, character: measure(this.text.slice(start, within), this.encoding) };
  }

  /**
   * The UTF-16 offset of a protocol position. A line outside the text clamps to its nearest end and
   * a character past the end of its line clamps to that line's end.
   */
  offsetAt(position: ProtocolPosition): number {
    // NaN, not finiteness: an infinite line or character clamps to an end like any other overshoot.
    if (Number.isNaN(position.line) || position.line < 0) return 0;
    if (position.line >= this.lineStarts.length) return this.text.length;
    const line = Math.floor(position.line);
    const start = this.lineStarts[line] ?? 0;
    const end = this.lineEnds[line] ?? this.text.length;
    if (Number.isNaN(position.character) || position.character <= 0) return start;
    return start + offsetWithinLine(this.text.slice(start, end), position.character, this.encoding);
  }

  /** Convert a service region to a protocol range. */
  rangeOf(region: ServiceRegion): ProtocolRange {
    return { start: this.positionAt(region.start), end: this.positionAt(region.end) };
  }

  /** Clamp into the text and off the tail half of a surrogate pair. Never throws. */
  private clampOffset(offset: number): number {
    if (Number.isNaN(offset) || offset <= 0) return 0;
    if (offset >= this.text.length) return this.text.length;
    const here = Math.floor(offset);
    const unit = this.text.charCodeAt(here);
    const previous = this.text.charCodeAt(here - 1);
    const splitsPair =
      unit >= 0xdc00 && unit <= 0xdfff && previous >= 0xd800 && previous <= 0xdbff;
    return splitsPair ? here - 1 : here;
  }

  /** Index of the line containing an in-range offset, by binary search over the line starts. */
  private lineOf(offset: number): number {
    let low = 0;
    let high = this.lineStarts.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if ((this.lineStarts[middle] ?? 0) <= offset) {
        low = middle;
      } else {
        high = middle - 1;
      }
    }
    return low;
  }
}
