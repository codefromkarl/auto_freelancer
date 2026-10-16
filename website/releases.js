"use strict";
(async () => {
  const root = document.getElementById("release-list");
  const targets = [
    ["windows", "x64", "Windows x64"],
    ["macos", "arm64", "macOS · Apple Silicon"],
    ["macos", "x64", "macOS · Intel"],
  ];
  let catalog = { releases: [] };
  try {
    const r = await fetch("releases.json", { cache: "no-store" });
    if (r.ok) catalog = await r.json();
  } catch {}
  root.replaceChildren();
  for (const [platform, architecture, title] of targets) {
    const row = document.createElement("article");
    row.className = "release";
    const h = document.createElement("h3");
    h.textContent = title;
    row.append(h);
    const r = catalog.releases.find(
      (x) =>
        x.platform === platform &&
        x.architecture === architecture &&
        x.native_verified === true &&
        x.code_signed === true &&
        (platform !== "macos" || x.notarized === true),
    );
    const p = document.createElement("p");
    p.textContent = r
      ? `Verified release ${r.version}`
      : "Native verification and signed public release are pending.";
    row.append(p);
    if (r) {
      try {
        const u = new URL(r.url);
        if (u.protocol !== "https:" || u.username || u.password) throw Error();
        const a = document.createElement("a");
        a.href = u.href;
        a.textContent = "Download installer";
        a.rel = "noopener";
        row.append(a);
      } catch {
        p.textContent = "Release URL is invalid. No download is offered.";
      }
    }
    root.append(row);
  }
})();
