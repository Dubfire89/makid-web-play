# MAKID Web Play

MAKID Web Play is a static GitHub Pages app for browsing and playing audio files from a MAKID library stored in Google Drive.

The app itself is public, but the music library JSON should be private. The browser only loads the track list after Google Drive login by fetching a private `WebAudioFile.json` file through the Google Drive API.

## What Is Public

These files can be public:

- The web app source code.
- The Web OAuth Client ID.
- The Google Drive file ID for the private library JSON.

These files should not be public:

- `MAKID.db`
- Google OAuth client secrets.
- Desktop OAuth credential JSON files.
- `WebAudioFile.json` with project names, track names, tags, genres, and Drive file IDs.

`public/WebAudioFile.json` is ignored on purpose and should not be committed.

## Local Setup

Install dependencies:

```bash
npm install
```

Create local env config:

```bash
cp .env.example .env.local
```

Edit `.env.local`:

```bash
VITE_GOOGLE_CLIENT_ID=your-web-oauth-client-id.apps.googleusercontent.com
VITE_LIBRARY_FILE_ID=your-private-webaudiofile-json-drive-file-id
VITE_BASE_PATH=/makid-web-play/
```

Run the app:

```bash
npm run dev
```

With the current GitHub Pages base path, local dev is available at:

```text
http://127.0.0.1:5173/makid-web-play/
```

## Google OAuth Setup

Create a Google Cloud project and enable the Google Drive API.

Create a Web OAuth client and add these Authorized JavaScript origins:

```text
http://127.0.0.1:5173
http://localhost:5173
https://your-github-username.github.io
```

Replace the GitHub Pages origin with the account or organization that hosts the site, for example:

```text
https://theirname.github.io
```

Do not put a path like `/makid-web-play/` in the OAuth origin.

## Private Library JSON

The app expects a private Google Drive file containing the exported MAKID web library JSON.

The publisher creates this file automatically. It writes a local copy here:

```text
~/Library/Application Support/makid/web_export/WebAudioFile.json
```

Then it creates or updates a private Google Drive file at the configured Drive path.

The first time the publisher creates the Drive file, it writes the new file ID into:

```text
.env.local
.env.production
```

After that, future publisher runs update the same private Drive file in place.

The default Drive path can be configured in `.env.local`:

```bash
MAKID_LIBRARY_DRIVE_PATH=MAKID_WEB/WebAudioFile.json
```

Example Drive URL:

```text
https://drive.google.com/file/d/1abcDEF_file_id_here/view
```

The file ID is:

```text
1abcDEF_file_id_here
```

Random visitors can open the public site, but they will not see the track list unless their Google account can read that private Drive JSON file.

## Exporting Data

Run the current MAKID exporter:

```bash
npm run publish:data
```

That script reads the local MAKID database, resolves Google Drive file IDs, and writes `WebAudioFile.json`.

It also uploads the JSON to a private Google Drive file. No manual copy into Google Drive is needed.

By default, unchanged audio rows reuse their previous Google Drive file IDs from the last local export, so repeated runs avoid unnecessary Drive lookup API calls.

By default, the exporter uses:

```text
~/Library/Application Support/makid/MAKID.db
~/Library/Application Support/makid/google_credentials.json
~/My Drive/
```

You can override those paths with environment variables:

```bash
MAKID_SOURCE_DB=/path/to/MAKID.db
MAKID_GOOGLE_CREDENTIALS_JSON=/path/to/google_credentials.json
MAKID_GOOGLE_DRIVE_ROOT=/path/to/My Drive
```

Upload settings can also be configured:

```bash
MAKID_UPLOAD_LIBRARY_JSON=1
MAKID_REUSE_DRIVE_LOOKUPS=1
MAKID_LIBRARY_DRIVE_PATH=MAKID_WEB/WebAudioFile.json
MAKID_LIBRARY_DRIVE_FILE_NAME=WebAudioFile.json
MAKID_LIBRARY_DRIVE_FOLDER_ID=optional-google-drive-folder-id
```

If `VITE_LIBRARY_FILE_ID` is empty, the publisher creates the private Drive JSON file and fills in `VITE_LIBRARY_FILE_ID` for you. Commit and push `.env.production` after that so GitHub Pages knows which private Drive file to request.

The exporter does not copy `WebAudioFile.json` into `public/` unless `MAKID_COPY_TO_WEB_APP_FOLDER` is set. The app no longer uses a public copy.

## Automatic Publishing On Mac

The app includes an optional macOS LaunchAgent installer. It runs without VS Code.

Run `npm run publish:data` manually once before installing, so Google OAuth is already approved and the private Drive JSON file exists.

Install it:

```bash
npm run auto:install
```

This watches the local MAKID database file and also checks every five minutes. Before publishing, it fingerprints the `File` table. If the `File` table did not change, it skips `publish:data`.

Logs are written to:

```text
~/Library/Logs/makid-web-play-publish.log
~/Library/Logs/makid-web-play-publish-error.log
```

Uninstall it:

```bash
npm run auto:uninstall
```

## GitHub Pages Deployment

Deployment is handled by `.github/workflows/deploy-pages.yml`.

Before deploying a fork:

1. Edit `.env.production`.
2. Set `VITE_GOOGLE_CLIENT_ID`.
3. Set `VITE_LIBRARY_FILE_ID`.
4. Set `VITE_BASE_PATH` to the repository path, for example:

```bash
VITE_BASE_PATH=/makid-web-play/
```

Then push to `main`. GitHub Actions builds the Vite app and deploys `dist/` to GitHub Pages.

## Commands

```bash
npm run dev
npm run build
npm run preview
npm run publish:data
npm run auto:install
npm run auto:uninstall
```
