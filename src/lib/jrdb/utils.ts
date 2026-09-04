import iconv from "iconv-lite";
import fs from "fs";

export type FieldDef = {
  name: string;
  start: number;
  length: number;
  type: "string" | "number" | "float";
};

/**
 * Shift_JISエンコードされたファイルをUTF-8テキストとして読み込む
 */
export function readShiftJisFile(filePath: string): string {
  const buffer = fs.readFileSync(filePath);
  return iconv.decode(buffer, "Shift_JIS");
}

/**
 * 固定長テキストの1行からフィールドを抽出する（バイト単位）
 */
export function extractField(
  lineBuffer: Buffer,
  start: number,
  length: number
): string {
  const slice = lineBuffer.subarray(start, start + length);
  return iconv.decode(slice, "Shift_JIS").trim();
}

/**
 * 固定長テキスト行をフィールド定義に基づいてパースする（バイト単位）
 */
export function parseLine(
  lineBuffer: Buffer,
  fields: FieldDef[]
): Record<string, string | number | null> {
  const result: Record<string, string | number | null> = {};

  for (const field of fields) {
    const raw = extractField(lineBuffer, field.start, field.length);

    if (raw === "" || raw === null) {
      result[field.name] = null;
      continue;
    }

    switch (field.type) {
      case "number": {
        const n = parseInt(raw, 10);
        result[field.name] = isNaN(n) ? null : n;
        break;
      }
      case "float": {
        const f = parseFloat(raw);
        result[field.name] = isNaN(f) ? null : f;
        break;
      }
      default:
        result[field.name] = raw;
    }
  }

  return result;
}

/**
 * ファイルをバイト単位の固定長行として分割する
 */
export function splitFileIntoLines(
  filePath: string,
  lineByteLength: number
): Buffer[] {
  const buffer = fs.readFileSync(filePath);
  const lines: Buffer[] = [];

  let offset = 0;
  while (offset + lineByteLength <= buffer.length) {
    lines.push(buffer.subarray(offset, offset + lineByteLength));
    offset += lineByteLength;
    // 改行コード（CR+LF or LF）をスキップ
    while (
      offset < buffer.length &&
      (buffer[offset] === 0x0d || buffer[offset] === 0x0a)
    ) {
      offset++;
    }
  }

  return lines;
}

/**
 * テキストファイルを行ごとに分割して読み込む（改行区切り）
 */
export function readFileLines(filePath: string): Buffer[] {
  const buffer = fs.readFileSync(filePath);
  const lines: Buffer[] = [];
  let start = 0;

  for (let i = 0; i < buffer.length; i++) {
    if (buffer[i] === 0x0a) {
      let end = i;
      if (end > start && buffer[end - 1] === 0x0d) {
        end--;
      }
      if (end > start) {
        lines.push(buffer.subarray(start, end));
      }
      start = i + 1;
    }
  }

  if (start < buffer.length) {
    lines.push(buffer.subarray(start));
  }

  return lines;
}

/**
 * JRDBの競馬場コードを名前に変換
 */
export const VENUE_CODES: Record<string, string> = {
  "01": "札幌",
  "02": "函館",
  "03": "福島",
  "04": "新潟",
  "05": "東京",
  "06": "中山",
  "07": "中京",
  "08": "京都",
  "09": "阪神",
  "10": "小倉",
};

/**
 * トラックコードを馬場種別に変換
 */
export function parseSurface(code: string): string {
  switch (code) {
    case "1":
      return "芝";
    case "2":
      return "ダート";
    case "3":
      return "障害";
    default:
      return code;
  }
}

/**
 * 馬場状態コードを文字列に変換
 */
export function parseCondition(code: string): string {
  switch (code) {
    case "1":
      return "良";
    case "2":
      return "稍重";
    case "3":
      return "重";
    case "4":
      return "不良";
    default:
      return code;
  }
}
