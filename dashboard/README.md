# Hosted dashboard

A password-protected page for running the engine from anywhere: see what is
queued (and watch it), pull a post back, edit the lineup, captions and
settings, pause or resume a campaign, and start a render, a push, a check or a
metrics refresh.

It is one static page (`index.html`) and one server function
(`functions/api/[[path]].js`). The function is the only thing holding a
credential, and it can do exactly four things against fixed allowlists: read
campaign files, write the files a person edits, start a workflow, list recent
runs. Uploading clips and previewing samples stay in the local dashboard
(`./ugc web`), which has your files and ffmpeg.

## Deploy on Cloudflare Pages

1. **Cloudflare → Workers & Pages → Create → Pages → Connect to Git**, pick
   `nickdotname/ugc-factory`.
   - Production branch: `main`
   - Build command: *(leave empty)*
   - Build output directory: `dashboard`
   - Root directory: `dashboard`
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
node --test dashboard/test/api.test.mjs
```

The dev server runs the real function against this checkout's files with
GitHub stubbed out: nothing is read from or written to the network.
