/**
 * Posting dashboard for the LinkedIn agent. It lives inside the Google Sheet.
 *
 * - The dashboard (a web app) lists posts. Each can be edited, scheduled, posted now or
 *   rejected, and today's draft can be written on demand.
 * - Every 5 minutes, checkDue() looks for approved posts whose "Post at" time has come and
 *   asks GitHub to publish them. GitHub runs only when something is due.
 *
 * Setup is in the README, "Posting dashboard".
 */

const REPO = 'Goku-Super-Saiyan/linkedin-sales-agent';
const WORKFLOW = 'daily-post.yml';
const TAB = 'Posts';
const TZ = 'Asia/Kolkata';
const MAX_POSTS_PER_DAY = 1; // Keep in step with schedule.max_posts_per_day in config/company.yaml.
const DISPATCH_GAP_MS = 4 * 60 * 1000;

// Run once from the editor.
function install() {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('SHEET_ID', SpreadsheetApp.getActive().getId());
  ScriptApp.getProjectTriggers().forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkDue').timeBased().everyMinutes(5).create();
  const sheet = sheet_();
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  if (headers.indexOf('Post at') < 0) {
    // The agent adds these on its next run too; adding them here lets the dashboard work today.
    ['Published at', 'Post at'].filter((h) => headers.indexOf(h) < 0).forEach((h) => {
      const col = sheet.getLastColumn() + 1;
      if (col > sheet.getMaxColumns()) sheet.insertColumnAfter(sheet.getMaxColumns());
      sheet.getRange(1, col).setValue(h);
    });
  }
  sheet.getRange(2, col_(sheet, 'Post at'), sheet.getMaxRows() - 1, 1).setNumberFormat('@');
}

function doGet() {
  sheet_(); // Only people who can open the sheet can use the dashboard.
  return HtmlService.createHtmlOutputFromFile('Dashboard')
    .setTitle('LinkedIn posts')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// ---- Called from the dashboard ----

function getPosts() {
  const sheet = sheet_();
  const values = sheet.getDataRange().getDisplayValues();
  const headers = values.shift();
  const key = { 'ID': 'id', 'Date': 'date', 'Status': 'status', 'Topic': 'topic',
    'Post text': 'text', 'Sources': 'sources', 'Notes': 'notes', 'LinkedIn link': 'link',
    'Published at': 'publishedAt', 'Post at': 'postAt' };
  const posts = values
    .filter((row) => row[0])
    .map((row) => {
      const post = {};
      headers.forEach((h, i) => { if (key[h]) post[key[h]] = row[i]; });
      return post;
    })
    .reverse()
    .slice(0, 30);
  return { posts, now: now_(), maxPerDay: MAX_POSTS_PER_DAY };
}

function savePost(id, text, postAt) {
  update_(id, { 'Post text': text, 'Post at': clean_(postAt) });
}

function schedulePost(id, text, postAt) {
  update_(id, { 'Post text': text, 'Post at': clean_(postAt), 'Status': 'Approved', 'Notes': '' });
  if (!clean_(postAt) || clean_(postAt) <= now_()) dispatch_('publish');
}

function postNow(id, text) {
  update_(id, { 'Post text': text, 'Post at': now_(), 'Status': 'Approved', 'Notes': '' });
  dispatch_('publish');
}

function setStatus(id, status) {
  if (['Pending review', 'Rejected'].indexOf(status) < 0) throw new Error('Unknown status ' + status);
  update_(id, { 'Status': status });
}

function draftNow() {
  sheet_();
  dispatch_('draft');
}

// ---- Every 5 minutes ----

function checkDue() {
  const sheet = sheet_();
  const values = sheet.getDataRange().getDisplayValues();
  const headers = values.shift();
  const status = headers.indexOf('Status');
  const postAt = headers.indexOf('Post at');
  const publishedAt = headers.indexOf('Published at');
  const now = now_();
  const today = now.slice(0, 10);
  const postedToday = values.filter((r) => r[status] === 'Published' && r[publishedAt].startsWith(today)).length;
  if (postedToday >= MAX_POSTS_PER_DAY) return;
  const due = values.some((r) => r[status].trim().toLowerCase() === 'approved'
    && (!r[postAt] || r[postAt].replace('T', ' ') <= now));
  const last = Number(PropertiesService.getScriptProperties().getProperty('LAST_DISPATCH') || 0);
  // Give the last run time to finish before asking again.
  if (due && Date.now() - last > DISPATCH_GAP_MS) dispatch_('publish');
}

// ---- Helpers ----

function sheet_() {
  const id = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (!id) throw new Error('Run install() from the Apps Script editor first.');
  const sheet = SpreadsheetApp.openById(id).getSheetByName(TAB);
  if (!sheet) throw new Error('The sheet has no "' + TAB + '" tab yet. Run the draft once first.');
  return sheet;
}

function col_(sheet, header) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const index = headers.indexOf(header);
  if (index < 0) throw new Error('Column "' + header + '" is missing. Run the agent once to add it.');
  return index + 1;
}

function update_(id, changes) {
  const sheet = sheet_();
  const ids = sheet.getRange(1, 1, sheet.getLastRow(), 1).getDisplayValues().map((r) => r[0]);
  const row = ids.indexOf(id) + 1;
  if (row < 2) throw new Error('Post ' + id + ' not found.');
  const current = sheet.getRange(row, col_(sheet, 'Status')).getValue();
  if (['Publishing', 'Published'].indexOf(current) >= 0) {
    throw new Error('This post is already ' + current.toLowerCase() + '.');
  }
  Object.keys(changes).forEach((header) => {
    const cell = sheet.getRange(row, col_(sheet, header));
    if (header === 'Post at') cell.setNumberFormat('@');
    cell.setValue(changes[header]);
  });
  SpreadsheetApp.flush();
}

function now_() {
  return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm');
}

// "2026-10-12T10:30" from the date picker becomes "2026-10-12 10:30".
function clean_(postAt) {
  return String(postAt || '').trim().replace('T', ' ');
}

function dispatch_(command) {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Add the script property GITHUB_TOKEN first.');
  const resp = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches',
    {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main', inputs: { command: command } }),
      muteHttpExceptions: true,
    },
  );
  if (resp.getResponseCode() !== 204) {
    throw new Error('GitHub returned ' + resp.getResponseCode() + ': ' + resp.getContentText());
  }
  props.setProperty('LAST_DISPATCH', String(Date.now()));
}
