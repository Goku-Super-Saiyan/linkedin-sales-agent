# LinkedIn Sales Agent

An assistant for 360 Degree Cloud's business development team on LinkedIn.

**Built so far: workflow 1, the daily post.**

1. **08:00 IST:** the agent reads fresh Salesforce and AI news, picks the most useful story, and writes a post in her voice. It adds the post to a Google Sheet as **Pending review**.
2. **Around 13:00 IST:** she reads the draft in the sheet, edits the text if she wants, and sets **Status** to **Approved** (or **Rejected**).
3. **Hourly, 13:15–19:15 IST, or right away with [instant posting](#5-instant-posting-optional):** the agent publishes approved posts to her LinkedIn profile, at most one a day, and adds the post link to the sheet.

Nothing is posted without her approval. Until LinkedIn is connected, approved posts are marked **Post manually** so she can copy and paste them.

## The Google Sheet

Each row in the **Posts** tab is one draft:

| Column | Meaning |
|---|---|
| Date | Day the draft was written |
| Status | `Pending review` → she sets `Approved` or `Rejected` → the agent sets `Publishing`, then `Published` (or `Failed`) |
| Topic | What the post is about |
| Post text | The post itself. Edit it freely before approving. |
| Sources | The news articles it is based on |
| Notes | Messages from the agent, for example a failure reason or a sign-in reminder |
| LinkedIn link | Link to the published post |

If a row says **Failed**, the note says why. Fix the problem and set Status back to **Approved**.

## Setup

All settings are GitHub secrets. Go to **Settings → Secrets and variables → Actions** in this repo.

### 1. Free AI key (Gemini)

1. Go to [Google AI Studio](https://aistudio.google.com/apikey) and click **Create API key**.
2. Save it as the secret `GEMINI_API_KEY`.

On the free tier, Google may use the prompts to improve its products. The agent only sends public news and the company profile in `config/company.yaml`, never private data.

### 2. Google Sheet

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project. Then enable the **Google Sheets API** in **APIs & Services → Library**.
2. Go to **IAM & Admin → Service accounts → Create service account**. No roles are needed. Open the account, then choose **Keys → Add key → JSON**. A file downloads.
3. Save the whole contents of that file as the secret `GOOGLE_SERVICE_ACCOUNT_JSON`. Then delete the file from your computer.
4. Create a Google Sheet and share it, as **Editor**, with the service account's email address (it ends in `iam.gserviceaccount.com`). Share it with your sister too.
5. Copy the sheet ID from its URL (`docs.google.com/spreadsheets/d/<THIS PART>/edit`) and save it as the secret `SHEET_ID`.

The agent creates the **Posts** tab and the Status dropdown the first time it runs.

### 3. Try it

Go to **Actions → Daily LinkedIn post → Run workflow**, choose `draft`, and run it. A draft should appear in the sheet within a minute or two. After that it runs on its own every morning.

### 4. Connect LinkedIn (when ready)

This step lets the agent publish by itself. Until it's done, everything else still works, and she posts approved drafts by hand.

1. At [LinkedIn Developers](https://www.linkedin.com/developers/apps/new), create an app. LinkedIn requires the app to be linked to a company page, so choose the 360 Degree Cloud page. A page admin has to approve the link.
2. On the app's **Products** tab, add **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**.
3. On the **Auth** tab, add the redirect URL `http://localhost:8765/callback`. Copy the **Client ID** and **Client Secret**.
4. On a computer with this repo and Python installed, run:
   ```bash
   pip install requests
   LINKEDIN_CLIENT_ID=... LINKEDIN_CLIENT_SECRET=... python scripts/linkedin_auth.py
   ```
   Your sister signs in with her LinkedIn account in the browser window that opens and clicks **Allow**.
5. The script prints three values. Save them as the secrets `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN` and `LINKEDIN_TOKEN_EXPIRES_ON`.

LinkedIn sign-ins last about 60 days. A week before expiry, the agent adds a reminder in the sheet's Notes column. Repeat step 4 and update the three secrets.

### 5. Instant posting (optional)

By default, approved posts go out at the next hourly run (13:15–19:15 IST). To post as soon as she sets **Approved**:

1. On GitHub, open **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**. Under **Repository access**, choose only this repository. Under **Permissions**, set **Actions** to **Read and write**. Copy the token.
2. In the Google Sheet, open **Extensions → Apps Script**. Replace the code with the contents of [`scripts/approve_trigger.gs`](scripts/approve_trigger.gs) and save.
3. In Apps Script, open **Project Settings** (the gear icon). Under **Script properties**, add `GITHUB_TOKEN` with the token as its value.
4. Back in the editor, pick `install` in the function dropdown and click **Run**. Google asks for permission; allow it. You may need to click **Advanced → Go to project** first.

Now, setting **Status** to **Approved** starts publishing within about a minute. The hourly run stays on as a backup, and the one-post-a-day limit still applies.

### Switching to a paid AI model (optional)

To use Claude instead of Gemini:

1. Add the secret `ANTHROPIC_API_KEY`.
2. Add the repository **variable** (not a secret) `LLM_PROVIDER` with the value `claude`.

To pin a specific model, set the variable `LLM_MODEL`.

## Changing what it writes about

Edit [`config/company.yaml`](config/company.yaml). It holds the company description, tone, topics to avoid, keywords, news feeds and fallback topics.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
# Local dry run without a Google Sheet:
GEMINI_API_KEY=... LOCAL_STORE_PATH=local_posts.json .venv/bin/python -m agent draft
```

Code layout: `agent/feeds.py` (news), `agent/content.py` (prompting and draft checks), `agent/llm.py` (AI providers), `agent/store.py` (Google Sheet), `agent/linkedin.py` (publishing), `agent/daily_post.py` (the workflow).

## Coming next

- **Leads:** find 10–15 ICP prospects a day and save them to a **Leads** tab. Waiting on the lead data source.
- **Replies:** she pastes a LinkedIn message, and the agent drafts a reply.
- **Connection notes:** personalized notes for her to send.

LinkedIn's API doesn't allow apps to search people, read messages or send invitations. Those workflows will prepare drafts, and she sends them herself.
