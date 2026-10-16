# BidMaster Local

A local-first, bring-your-own-key project and proposal workbench. The website sells software access; model requests are made from the customer's device directly to their selected HTTPS model endpoint. This is a new distribution mode, not a change to the existing personal scheduler.

## Run a development preview

Use Python 3.12 in a separate environment:

```sh
python -m pip install -r desktop/requirements-lock.txt
python -m desktop.launcher
```

For source-development licensing, first generate an isolated test issuer using the publisher CLI below, then run `python -m desktop.launcher --publisher-public-key /secure/test-issuer/issuer-public.pem`. Import a signed trial for the displayed installation ID. The private key stays outside the checkout. Installed builds reject this identity override and use only the public key embedded by their builder.

The launcher opens an authenticated loopback browser session and manages a single local executor. Customers of the eventual native installers do not need to install Python or Node. Windows x64 and macOS 15+ Intel/Apple Silicon are the initial native verification targets. Do not describe them as verified until the corresponding native jobs pass.

No `.env`, account token, publisher private key, portfolio or existing database is included in a native build. A first launch can open and import a project with no credentials. Model tasks need a saved OS-vault key, skills, model ID, explicit usage confirmation and a valid signed software license.

## First use

1. V1 supports the OpenAI-compatible protocol, not arbitrary provider-specific APIs. Save the exact HTTPS endpoint and model ID you are allowed to use. Re-enter a key if changing its destination. Saving does not contact a provider. The optional access check uses `GET /models`; it is not a generation test and provider accounting may apply.
2. Save your own skills, background and economic limits. The original developer's resume and examples are not used.
3. Import a complete brief you have permission to process. V1 manual imports are fixed-price USD projects, not live platform listings. No platform request is made by import, assessment, or proposal generation.
4. Import a publisher-signed trial or personal license for the displayed installation ID. The OS vault must be available; there is no plaintext fallback.
5. Analyze the project, review concerns, and generate a validated proposal only when ready. Copy/export and review before submitting. A task can make bounded additional requests for quality; the task limit is not a monetary cap.

Analysis and proposal quality use the existing engine. The desktop adapter never reads the developer's `.env`, personal resume or business integrations. Manual project IDs are negative and are excluded from the optional platform worker.

## Data and credentials

- Windows: `%LOCALAPPDATA%\BidMaster`
- macOS: `~/Library/Application Support/BidMaster`
- Linux development: `$XDG_DATA_HOME/bidmaster`, or `~/.local/share/bidmaster`

Keys are held in Windows Credential Manager, macOS Keychain or the Linux Secret Service. Missing/locked vaults block credential persistence rather than falling back to a file. Model keys and platform tokens are never returned to the browser or sent to a publisher relay. Project text/background still goes to the selected cloud model when the user requests a task.

`config.json` contains non-secret settings. `projects.db` contains projects, results and durable jobs. `session.json` is an owner-private transient local UI session, not a model key. Logs stay local; safe diagnostics deliberately omit credentials, project contents, prompts and raw logs. Keep the data directory private and never place it in a public/shared folder.

Use the launcher again to reopen an existing session without creating a second executor. Pausing stops new queued work, not an in-flight request. Interrupted analysis tasks are not automatically resent after restart. Removing keys, expiration and uninstall preserve results and submission receipts.

## Platform integration is a separate capability

A software license is not permission to automate a third-party platform. Access requires both a software license containing `platform_execution` and a separate signed `platform_authorization` document with a publisher-verified reference to actual written Freelancer permission. The customer's own account token and explicit execution choice are also required. The publisher must not issue the attestation without verifying that permission.

The worker defaults to preview and reuses the existing frozen-content, account/quote checks and persistent per-project submission claims. Unknown submission outcomes never unlock/resend. No award acceptance, money movement or customer-message sending is exposed in this app. One data directory is bound to an account once submission history exists; switching to another account requires a separate directory, never deleting the old ledger.

The worker runs only while the device is awake/online. Closing the browser does not stop it; use Stop safely or Quit safely. The launcher waits for the current task and receipt processing before exit. Do not terminate the process during a transaction.

## Native builds

Build on the actual target OS/architecture. The CI matrix is Windows Server 2022 x64 (installer verification), macOS 15 arm64 and macOS 15 Intel. Actual Windows desktop user acceptance remains an additional release check.

```sh
python -m pip install -r desktop/requirements-build.txt
python -m desktop.build --issuer-public-key /secure/path/issuer-public.pem --output dist/local --installer
```

Windows needs Inno Setup 6 for its per-user installer. macOS creates `.app` and `.dmg` with an Applications shortcut. User data lives outside the installation and is preserved by upgrade/uninstall. The unsigned CI workflow uses a disposable **test** issuer; those artifacts are development previews, not commercial releases.

Optional production signing uses `--sign` plus an existing authorized certificate in the Windows store (`BIDMASTER_WINDOWS_CERT_SHA1`) or an existing Developer ID identity (`BIDMASTER_MAC_SIGN_IDENTITY`). macOS notarization uses `--notarize-profile` with an already configured notarytool keychain profile. No developer account, certificate, subscription, or CI resource is created or purchased by these scripts.

Run the actual executable:

```sh
python -m desktop.native_smoke --executable /path/to/BidMaster
```

On Windows use `BidMaster.exe`; on macOS use `BidMaster.app/Contents/MacOS/BidMaster`. The smoke check covers native credential-vault roundtrip, manual import, safe exit, restart and data preservation without any model/platform requests. It must run independently on each target; a Linux result is not Windows/macOS evidence.

## Publisher licensing

Keep the private key outside all source and release directories:

```sh
python -m desktop.issuer keygen --directory /secure/publisher-keys
python -m desktop.issuer issue --key /secure/publisher-keys/issuer-private.pem \
  --installation CUSTOMER_INSTALLATION_ID --days 14 --output customer-trial.json
```

Never replace an existing publisher identity casually. Supply only its public key to the builder. A verified paid order can be followed by an annual license (`--days 365`). No active checkout or automatic merchant webhook is claimed: commercial entity, merchant approval, pricing/refunds and verified order/webhook mapping are release dependencies.

The same CLI can issue platform attestations only after written permission is checked, or signed revocation lists. Offline licenses expire at their signed deadline; revocation is effective when a new signed revocation list is imported. Instant offline revocation is not promised.

## Updates and recovery

Only newer signed update metadata for the device's OS/architecture, production code signing and (on macOS) notarization is accepted. Downloads are direct HTTPS, bounded, no redirects and verified against the signed size/SHA-256. The app does not silently install executable code. Quit safely before opening the verified native installer; the old program/data remain available if verification fails.

`desktop.release` creates public signed metadata only after matching native verification and production signing. Native verification and final payment/platform permissions are independent of local tests. Never publish issuer private keys or temporary trial-signing material.

A local online backup is available in Settings. Do not restore an old database over newer submission claims. Reconcile later bids/unknown outcomes first. Backups and updates are not permission to resend a bid.

The Windows installer checks the running-app mutex and does not forcibly close a running app. Safe updates do not cancel in-flight work. A recovered orphan platform worker is detected by the per-directory runtime lock; a stale PID record alone does not establish ownership. All installed-file replacements and OS credential backends still require the corresponding native CI/desktop acceptance, not just source-level tests.
