# Local-product website source

Buildless HTML/CSS/JS for an English private-preview product page. Serve this directory with a static server to inspect it. No forms collect emails or keys, no analytics is enabled, and no fake checkout or unverified download links are offered.

`releases.json` is deliberately an empty factual release inventory until matching native builds, code signing/notarization and public asset URLs exist. After verification, generate it with `python -m desktop.catalog`; do not manually mark an unsigned preview as production-ready. A website listing is not evidence of native app acceptance.

Public deployment is deferred until the product owner supplies brand/domain, legal/commercial details and a ready release. Use the Sites source workflow for a hosted deployment if that channel is selected; no personal repo state, issuer private key or customer data belongs in the website archive.
