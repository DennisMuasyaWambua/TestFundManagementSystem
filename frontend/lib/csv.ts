/**
 * A minimal RFC 4180 CSV parser for previewing an uploaded file in the browser.
 *
 * Handles quoted fields (with "" as an escaped quote) and both \n and \r\n line
 * endings. It is not meant to replace the backend's csv.DictReader -- just to let
 * someone see their rows before they commit to uploading them.
 */
export function parseCsvPreview(
  text: string,
  maxRows = 20,
): { headers: string[]; rows: string[][]; totalRows: number } {
  const records: string[][] = [];
  let field = "";
  let record: string[] = [];
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      record.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      record.push(field);
      field = "";
      if (record.length > 1 || record[0] !== "") records.push(record);
      record = [];
    } else {
      field += char;
    }
  }
  if (field !== "" || record.length > 0) {
    record.push(field);
    if (record.length > 1 || record[0] !== "") records.push(record);
  }

  const [headers = [], ...body] = records;
  return { headers, rows: body.slice(0, maxRows), totalRows: body.length };
}
