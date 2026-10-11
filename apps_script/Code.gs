/**
 * Posting dashboard for the LinkedIn agent. It lives inside the Google Sheet.
 *
 * - The dashboard (a web app) lists posts. Each can be edited, scheduled, posted now or
 *   rejected, and today's draft can be written on demand.
 * - Every 5 minutes, checkDue() looks for approved posts whose "Post at" time has come and
 *   asks GitHub to publish them. GitHub runs only when something is due.
 * - People sign in with a username and password. Logins are added from the sheet's
 *   Dashboard menu and stored as salted hashes in the script properties.
 *
 * Setup is in the README, "Posting dashboard".
 */

const REPO = 'Goku-Super-Saiyan/linkedin-sales-agent';
const WORKFLOW = 'daily-post.yml';
const TAB = 'Posts';
const TZ = 'Asia/Kolkata';
const SETTINGS_TAB = 'Settings';
// Used until someone saves the Settings panel. Same defaults as config/company.yaml.
const DEFAULT_SETTINGS = { defaultTime: '10:00', maxPerDay: 1 };
const DISPATCH_GAP_MS = 4 * 60 * 1000;
const SESSION_SECONDS = 6 * 60 * 60; // The longest CacheService keeps anything.
const MAX_FAILED_LOGINS = 5; // Per username, per 15 minutes.
const MAX_FAILED_LOGINS_ALL = 20; // Across all usernames, per 15 minutes.
const HASH_ROUNDS = 2000;

// Run once from the editor. (It fails if called from the dashboard, which has no active sheet.)
function install() {
  const sheetId = SpreadsheetApp.getActive().getId();
  const props = PropertiesService.getScriptProperties();
  props.setProperty('SHEET_ID', sheetId);
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
  return HtmlService.createHtmlOutputFromFile('Dashboard')
    .setTitle('LinkedIn posts')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// ---- Sheet menu: managing logins (only people who can edit the sheet see it) ----

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Dashboard')
    .addItem('Add or change a login', 'menuAddLogin')
    .addItem('Remove a login', 'menuRemoveLogin')
    .addItem('List logins', 'menuListLogins')
    .addToUi();
}

function menuAddLogin() {
  const ui = SpreadsheetApp.getUi();
  const name = ui.prompt('Username').getResponseText().trim().toLowerCase();
  if (!name) return;
  const password = ui.prompt('Password for ' + name + ' (at least 10 characters)').getResponseText();
  if (password.length < 10) {
    ui.alert('Password must be at least 10 characters. Nothing was changed.');
    return;
  }
  const users = users_();
  const salt = Utilities.getUuid();
  users[name] = { salt: salt, hash: hash_(salt, password) };
  saveUsers_(users);
  ui.alert('Login saved for ' + name + '. Anyone already signed in as ' + name + ' stays signed in until their session ends.');
}

function menuRemoveLogin() {
  const ui = SpreadsheetApp.getUi();
  const name = ui.prompt('Username to remove').getResponseText().trim().toLowerCase();
  const users = users_();
  if (!users[name]) {
    ui.alert('No login called ' + name + '.');
    return;
  }
  delete users[name];
  saveUsers_(users);
  ui.alert('Removed ' + name + '.');
}

function menuListLogins() {
  const names = Object.keys(users_());
  SpreadsheetApp.getUi().alert(names.length ? 'Logins: ' + names.join(', ') : 'No logins yet.');
}

// ---- Called from the dashboard. Every call except login needs a session token. ----

function login(username, password) {
  const name = String(username || '').trim().toLowerCase();
  const cache = CacheService.getScriptCache();
  const failKey = 'fail_' + Utilities.base64EncodeWebSafe(name);
  const fails = Number(cache.get(failKey) || 0);
  const failsAll = Number(cache.get('fail_all') || 0);
  if (fails >= MAX_FAILED_LOGINS || failsAll >= MAX_FAILED_LOGINS_ALL) {
    throw new Error('Too many wrong passwords. Try again in 15 minutes.');
  }
  const user = users_()[name];
  if (!user || hash_(user.salt, String(password || '')) !== user.hash) {
    cache.put(failKey, String(fails + 1), 15 * 60);
    cache.put('fail_all', String(failsAll + 1), 15 * 60);
    throw new Error('Wrong username or password.');
  }
  const token = Utilities.getUuid() + Utilities.getUuid();
  cache.put('session_' + token, name, SESSION_SECONDS);
  return { token: token, username: name };
}

function logout(token) {
  CacheService.getScriptCache().remove('session_' + token);
}

function getPosts(token) {
  const username = user_(token);
  const settings = settings_();
  const posts = rows_()
    .map((r) => ({ id: r.ID, date: r.Date, status: r.Status, topic: r.Topic, text: r['Post text'],
      sources: r.Sources, notes: r.Notes, link: r['LinkedIn link'], publishedAt: r['Published at'],
      postAt: r['Post at'] }))
    .reverse()
    .slice(0, 60);
  return { posts: posts, now: now_(), settings: settings, nextSlot: nextSlot_(rows_(), settings, ''),
    username: username };
}

function savePost(token, id, text, postAt) {
  user_(token);
  update_(id, { 'Post text': text, 'Post at': clean_(postAt) });
}

// Returns the time it was scheduled for ('' means right away).
function schedulePost(token, id, text, postAt) {
  user_(token);
  const when = clean_(postAt) || nextSlot_(rows_(), settings_(), id);
  update_(id, { 'Post text': text, 'Post at': when, 'Status': 'Approved', 'Notes': '' });
  if (!when || when <= now_()) dispatch_('publish');
  return when;
}

function postNow(token, id, text) {
  user_(token);
  update_(id, { 'Post text': text, 'Post at': now_(), 'Status': 'Approved', 'Notes': '' });
  dispatch_('publish');
}

function setStatus(token, id, status) {
  user_(token);
  if (['Pending review', 'Rejected'].indexOf(status) < 0) throw new Error('Unknown status ' + status);
  update_(id, { 'Status': status });
}

// Always writes one more draft, even if today's daily draft exists.
function draftNow(token) {
  user_(token);
  sheet_();
  dispatch_('new-draft');
}

// Saves the default post time and daily limit. With applyToAll, every scheduled post that
// hasn't gone out yet is moved onto the new times, earliest first.
function saveSettings(token, defaultTime, maxPerDay, applyToAll) {
  user_(token);
  const time = String(defaultTime || '').trim();
  if (time && !/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) throw new Error('Pick a valid time.');
  const max = Number(maxPerDay);
  if (!(max >= 1 && max <= 5)) throw new Error('Posts per day must be between 1 and 5.');
  const ss = SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('SHEET_ID'));
  const tab = ss.getSheetByName(SETTINGS_TAB) || ss.insertSheet(SETTINGS_TAB);
  tab.getRange(1, 1, 3, 2).setNumberFormat('@').setValues([
    ['Setting', 'Value'], ['default_post_time', time], ['max_posts_per_day', String(max)]]);
  SpreadsheetApp.flush();
  let moved = 0;
  if (applyToAll) {
    const settings = settings_();
    const rows = rows_();
    const now = now_();
    const toMove = rows
      .filter((r) => r.Status === 'Approved' && (!r['Post at'] || r['Post at'] > now))
      .sort((a, b) => (a['Post at'] || '').localeCompare(b['Post at'] || ''));
    toMove.forEach((r) => { r['Post at'] = ''; }); // Free their old slots before reassigning.
    toMove.forEach((r) => {
      r['Post at'] = nextSlot_(rows, settings, r.ID);
      update_(r.ID, { 'Post at': r['Post at'] });
      moved++;
    });
  }
  return { settings: settings_(), moved: moved };
}

// ---- Every 5 minutes ----

function checkDue() {
  const rows = rows_();
  const now = now_();
  const today = now.slice(0, 10);
  const postedToday = rows.filter((r) => r.Status === 'Published' && r['Published at'].startsWith(today)).length;
  if (postedToday >= settings_().maxPerDay) return;
  const due = rows.some((r) => r.Status.trim().toLowerCase() === 'approved'
    && (!r['Post at'] || r['Post at'].replace('T', ' ') <= now));
  const last = Number(PropertiesService.getScriptProperties().getProperty('LAST_DISPATCH') || 0);
  // Give the last run time to finish before asking again.
  if (due && Date.now() - last > DISPATCH_GAP_MS) dispatch_('publish');
}

// ---- Helpers ----

// Posts tab rows as objects keyed by header, oldest first.
function rows_() {
  const values = sheet_().getDataRange().getDisplayValues();
  const headers = values.shift();
  return values.filter((row) => row[0]).map((row) => {
    const r = {};
    headers.forEach((h, i) => { r[h] = row[i]; });
    r['Post at'] = (r['Post at'] || '').replace('T', ' ');
    r['Published at'] = r['Published at'] || '';
    return r;
  });
}

function settings_() {
  const ss = SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('SHEET_ID'));
  const tab = ss.getSheetByName(SETTINGS_TAB);
  const saved = {};
  if (tab) tab.getDataRange().getDisplayValues().forEach((r) => { saved[r[0]] = r[1]; });
  return {
    defaultTime: 'default_post_time' in saved ? saved.default_post_time : DEFAULT_SETTINGS.defaultTime,
    maxPerDay: Number(saved.max_posts_per_day) || DEFAULT_SETTINGS.maxPerDay,
  };
}

// The next default-time slot with room left under the daily limit, or '' for "right away"
// when no default time is set. Posts already published or scheduled fill the slots.
function nextSlot_(rows, settings, ignoreId) {
  if (!settings.defaultTime) return '';
  const busy = {};
  rows.forEach((r) => {
    if (r.ID === ignoreId) return;
    const day = r.Status === 'Published' ? r['Published at'].slice(0, 10)
      : (r.Status === 'Approved' || r.Status === 'Publishing') && r['Post at'] ? r['Post at'].slice(0, 10) : '';
    if (day) busy[day] = (busy[day] || 0) + 1;
  });
  const now = now_();
  const day = new Date(now.slice(0, 10) + 'T12:00:00Z');
  if (now.slice(0, 10) + ' ' + settings.defaultTime <= now) day.setUTCDate(day.getUTCDate() + 1);
  for (let i = 0; i < 366; i++) {
    const key = Utilities.formatDate(day, 'UTC', 'yyyy-MM-dd');
    if ((busy[key] || 0) < settings.maxPerDay) return key + ' ' + settings.defaultTime;
    day.setUTCDate(day.getUTCDate() + 1);
  }
  return '';
}

function user_(token) {
  const name = token && CacheService.getScriptCache().get('session_' + token);
  if (!name || !users_()[name]) throw new Error('SIGNED_OUT');
  return name;
}

function users_() {
  return JSON.parse(PropertiesService.getScriptProperties().getProperty('DASHBOARD_USERS') || '{}');
}

function saveUsers_(users) {
  PropertiesService.getScriptProperties().setProperty('DASHBOARD_USERS', JSON.stringify(users));
}

function hash_(salt, password) {
  let digest = salt + ':' + password;
  for (let i = 0; i < HASH_ROUNDS; i++) {
    digest = Utilities.base64Encode(
      Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, digest + salt, Utilities.Charset.UTF_8));
  }
  return digest;
}

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
