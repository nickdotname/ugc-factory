# Hosted dashboard

A password-protected page for running the engine from a phone or a laptop.

| tab | what it is for |
|---|---|
| **Schedule** | A checklist that walks a new campaign to its first post, then every video lined up, by day and time: what is on screen, the caption, which accounts, each account's own version. Watch one, or pull it back. |
| **Content** | Drop in a batch of videos and a batch of song clips; each post is built from a random pick of each. Write captions, switch a clip off, add another song. |
| **Plan** | Posts spelled out by hand: this clip, this second of the track, these words, this time. |
| **Setup** | Posting hours, sound, a different video per account, the link and closing lines every post carries, which accounts. The full settings file is at the bottom. |
| **Jobs** | Make videos now, send to Buffer now, check everything, refresh numbers, ask why something did not post. |

The pill at the top right says whether the campaign is **Paused**, in **Test
mode** or **Live**, and is how you change it. "New campaign…" is in the
campaign menu; a new campaign always starts paused.

**Adding videos and song clips** is drag and drop (or tap to choose) on the
Content tab. Dropped files go to a holding area; the `ingest` job then checks
each one really plays, gives it its proper name and adds it to the pool —
about two minutes, and the page updates itself. Files up to 95 MB each.

## How it is built

- `index.html`, `app.css`, `app.js` — the page. No build step.
- `lib/yamledit.js` — changes one setting in a config file in place, so the
  comments explaining every setting survive an edit from a form.
- `lib/bank.js` — reads and writes caption files.
- `lib/template.js` — the files a new campaign starts with.
- `functions/api/[[path]].js` — the only server code, and the only thing
  holding a credential. It works from fixed allowlists: which files can be
  read, which can be committed, which jobs can be started with which inputs.
  Saves are single commits made on top of the exact version that was edited,
  so a stale tab can never overwrite newer work.

## Deploy on Cloudflare Pages

1. **Cloudflare → Workers & Pages → Create → Pages → Connect to Git**, pick
   `nickdotname/ugc-factory`.
   - Production branch: `main`
   - Root directory (under "Advanced"): `dashboard`
   - Build command: *(leave empty)*
   - Build output directory: *(leave empty — the root directory is the site)*
2. **GitHub → Settings → Developer settings → Fine-grained tokens → Generate.**
   Repository access: only `ugc-factory`. Permissions: **Contents: Read and
   write**, **Actions: Read and write**. Nothing else.
3. In the Pages project: **Settings → Variables and Secrets**, add two
   *secrets* for Production:
   - `GITHUB_TOKEN` — the token from step 2
   - `DASH_PASSWORD` — a long password of your choosing
4. **Deployments → Retry deployment** so it picks the secrets up.
5. **Custom domains → Set up a domain** → e.g. `factory.nickbenak.com`.

Until both secrets exist the function refuses everything, so a half-finished
setup is closed, not open.

Changing `DASH_PASSWORD` signs every session out. To cut the dashboard off
entirely, revoke the GitHub token.

For a second lock, put Cloudflare Access (Zero Trust → Access → Applications)
in front of the domain and allow only your email.

## Work on it locally

```bash
node dashboard/test/dev-server.mjs     # http://localhost:8788, password: dev
node --test dashboard/test/api.test.mjs dashboard/test/lib.test.mjs
```

The dev server runs the real function against this checkout's files with
GitHub stubbed out. Saves stay in memory, so everything is safe to click.

## Media and the private repository

The repository is private, so the GitHub links its clips and rendered videos
are stored under only open for someone signed in to GitHub. The site serves
them instead:

- `/api/media?tag=…&name=…` — behind the login. What the Play buttons use.
- `/v/<render tag>/<id>.mp4` — no login, finished renders only, by exact
  random name. This is the link Buffer and the networks are given; the base
  address is `media_base_url` in `site.yaml` at the repo root.

Both use the same `GITHUB_TOKEN`; nothing new to set up. If the site is down,
posting stops (and says so) rather than queueing posts Buffer will reject.
