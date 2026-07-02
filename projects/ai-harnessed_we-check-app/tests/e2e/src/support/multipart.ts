export function buildCsv(rows: string[]): string {
  const header = "institutional_id,display_name,class_code,subject_code";
  return [header, ...rows].join("\n");
}

export function buildUserCsv(rows: string[]): string {
  const header = "institutional_id,display_name,email,role,active";
  return [header, ...rows].join("\n");
}

export function multipartPayload(
  csv: string,
  boundary = "----wecheck-e2e",
): { payload: string; contentType: string } {
  const payload =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="roster.csv"\r\n` +
    `Content-Type: text/csv\r\n\r\n` +
    `${csv}\r\n` +
    `--${boundary}--\r\n`;
  return {
    payload,
    contentType: `multipart/form-data; boundary=${boundary}`,
  };
}

export function multipartUserPayload(
  csv: string,
  boundary = "----wecheck-e2e-users",
): { payload: string; contentType: string } {
  const payload =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="users.csv"\r\n` +
    `Content-Type: text/csv\r\n\r\n` +
    `${csv}\r\n` +
    `--${boundary}--\r\n`;
  return {
    payload,
    contentType: `multipart/form-data; boundary=${boundary}`,
  };
}
