const QUEUE_SHEET = 'Blast Otomatis';
const DONE_SHEET = 'Selesai';
const HEADERS = ['Username', 'Pesan', 'Interval (detik)', 'ID', 'Diklaim pada', 'Status terakhir'];

function siapkan() {
  const file = SpreadsheetApp.getActive();
  const queue = file.getSheetByName(QUEUE_SHEET);
  if (!queue) throw new Error(`Tab ${QUEUE_SHEET} tidak ditemukan`);
  if (queue.getRange('A1').getValue() !== HEADERS[0]) {
    queue.insertRowsBefore(1, 2);
    queue.getRange('A2').setValue('Pengaturan');
  }
  queue.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
  queue.setFrozenRows(1);
  const done = file.getSheetByName(DONE_SHEET) || file.insertSheet(DONE_SHEET);
  if (!done.getLastRow()) done.appendRow([...HEADERS.slice(0, 3), 'Terkirim pada']);
}

function doPost(event) {
  const body = JSON.parse(event.postData.contents || '{}');
  authorize_(body.secret);
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    return body.action === 'claim' ? claim_(body.limit) : finish_(body.results || []);
  } finally {
    lock.releaseLock();
  }
}

function claim_(requestedLimit) {
  const limit = Math.min(500, Math.max(1, Number(requestedLimit) || 500));
  const sheet = SpreadsheetApp.getActive().getSheetByName(QUEUE_SHEET);
  const message = String(sheet.getRange('B2').getValue()).trim();
  const interval = Number(sheet.getRange('C2').getValue()) || 0;
  if (!message) return json_({items: []});
  const count = sheet.getLastRow() - 2;
  if (count < 1) return json_({items: []});
  const range = sheet.getRange(3, 1, count, HEADERS.length);
  const values = range.getValues();
  const now = new Date();
  const expired = new Date(now.getTime() - 30 * 60 * 1000);
  const items = [];
  values.forEach(row => {
    if (items.length >= limit || !row[0]) return;
    if (row[3] && row[4] && new Date(row[4]) > expired) return;
    const id = row[3] || Utilities.getUuid();
    row.splice(3, 3, id, now, 'Diproses');
    items.push({id, username: String(row[0]), message, interval});
  });
  range.setValues(values);
  return json_({items});
}

function finish_(rawResults) {
  const file = SpreadsheetApp.getActive();
  const queue = file.getSheetByName(QUEUE_SHEET);
  const done = file.getSheetByName(DONE_SHEET);
  const count = queue.getLastRow() - 2;
  if (count < 1) return json_({ok: true});
  const range = queue.getRange(3, 1, count, HEADERS.length);
  const values = range.getValues();
  const results = new Map(rawResults.filter(item => item.id).map(item => [String(item.id), item]));
  const completed = [];
  const remove = [];
  values.forEach((row, index) => {
    const result = results.get(String(row[3]));
    if (!result) return;
    if (result.status === 'sent') {
      completed.push([row[0], result.message, result.interval, new Date()]);
      remove.push(index + 3);
    } else {
      row.splice(3, 3, '', '', result.error || result.status);
    }
  });
  range.setValues(values);
  if (completed.length) {
    done.getRange(done.getLastRow() + 1, 1, completed.length, 4).setValues(completed);
  }
  deleteRows_(queue, remove);
  return json_({ok: true});
}

function deleteRows_(sheet, rows) {
  rows.sort((a, b) => b - a);
  let end = rows[0];
  let start = end;
  rows.slice(1).forEach(row => {
    if (row === start - 1) start = row;
    else {
      sheet.deleteRows(start, end - start + 1);
      start = end = row;
    }
  });
  if (start) sheet.deleteRows(start, end - start + 1);
}

function authorize_(secret) {
  const expected = PropertiesService.getScriptProperties().getProperty('SHEET_BLAST_SECRET');
  if (!expected || secret !== expected) throw new Error('Unauthorized');
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
