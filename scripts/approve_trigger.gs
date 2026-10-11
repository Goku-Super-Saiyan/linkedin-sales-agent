/**
 * Publish as soon as a post is approved.
 *
 * Paste this into the Google Sheet (Extensions -> Apps Script), save a GitHub token as the
 * script property GITHUB_TOKEN, then run `install` once. From then on, setting a row's
 * Status to "Approved" starts the publish workflow right away instead of waiting for the
 * hourly run. See README "Instant posting".
 */

const REPO = 'Goku-Super-Saiyan/linkedin-sales-agent';
const WORKFLOW = 'daily-post.yml';
const TAB = 'Posts';

function install() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'onStatusEdit')
    .forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('onStatusEdit').forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
}

function onStatusEdit(e) {
  const sheet = e.range.getSheet();
  if (sheet.getName() !== TAB || e.range.getRow() < 2) return;
  const header = sheet.getRange(1, e.range.getColumn()).getValue();
  if (header !== 'Status') return;
  if (String(e.range.getValue()).trim().toLowerCase() !== 'approved') return;
  publishNow();
}

function publishNow() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Add the script property GITHUB_TOKEN first.');
  const resp = UrlFetchApp.fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main', inputs: { command: 'publish' } }),
      muteHttpExceptions: true,
    },
  );
  if (resp.getResponseCode() !== 204) {
    throw new Error(`GitHub returned ${resp.getResponseCode()}: ${resp.getContentText()}`);
  }
}
