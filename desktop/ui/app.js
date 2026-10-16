"use strict";
let session =
  new URLSearchParams(location.hash.slice(1)).get("session") ||
  sessionStorage.getItem("bidmaster_session");
if (location.hash) history.replaceState(null, "", location.pathname);
if (session) sessionStorage.setItem("bidmaster_session", session);
const $ = (s) => document.querySelector(s);
let currentStatus = null,
  selectedTab = "setup";
function message(text, error = false) {
  const n = $("#notice");
  n.hidden = false;
  n.textContent = text;
  n.classList.toggle("error", error);
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    headers: {
      Authorization: "Bearer " + session,
      "Content-Type": "application/json",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) {
    const d = data.detail;
    throw new Error(
      typeof d === "string"
        ? d
        : Array.isArray(d)
          ? d.map((e) => `${e.field}: ${e.message}`).join("; ")
          : "The request failed.",
    );
  }
  return data;
}
async function perform(button, action) {
  button.disabled = true;
  try {
    await action();
  } catch (e) {
    message(e.message, true);
  } finally {
    button.disabled = false;
  }
}
function formData(form) {
  return Object.fromEntries(new FormData(form));
}
function fill(form, name, value) {
  form.elements.namedItem(name).value = value ?? "";
}
async function status(fillForms = false) {
  currentStatus = await api("/status");
  const s = currentStatus,
    c = s.config;
  $("#connection").textContent = !s.queue_alive
    ? "Local queue unavailable"
    : s.queue_busy
      ? "Task in progress"
      : "Local instance connected";
  $("#connection").classList.toggle("ready", s.queue_alive);
  $("#version").textContent = s.version;
  $("#installation").value = c.installation_id;
  $("#pause").textContent = c.queue_paused ? "Resume queue" : "Pause queue";
  $("#vault-status").textContent = s.vault.available
    ? `OS vault ready. Model key ${s.vault.provider_key_saved ? "saved" : "not saved"}.`
    : s.vault.message || "OS credential vault unavailable.";
  $("#license-status").textContent = s.license.active
    ? `Active until ${new Date(s.license.expires_at).toLocaleDateString()}`
    : s.license.message;
  $("#platform-permission").textContent = s.platform_permission.available
    ? "Read access authorized. Submission still requires its own permission and explicit mode."
    : s.platform_permission.message;
  $("#worker-status").textContent = s.platform.running
    ? `Running (PID ${s.platform.pid})`
    : "Not running";
  $("#data-location").textContent = `Local data: ${s.data_directory}`;
  if (fillForms) {
    const p = $("#profile-form");
    for (const [key, value] of Object.entries({
      name: c.profile.name,
      skills: c.profile.skills.join(", "),
      background: c.profile.background,
      rate: c.profile.minimum_net_hourly,
      amount: c.profile.maximum_amount,
      hours: c.profile.maximum_hours,
      daily: c.daily_model_tasks,
    }))
      fill(p, key, value);
    const f = $("#provider-form");
    fill(f, "endpoint", c.provider.base_url);
    fill(f, "model", c.provider.model);
    fill($("#account-form"), "account", c.freelancer_user_id);
  }
}
for (const button of document.querySelectorAll("[data-tab]"))
  button.onclick = () => {
    selectedTab = button.dataset.tab;
    for (const b of document.querySelectorAll("[data-tab]"))
      b.classList.toggle("selected", b === button);
    for (const t of document.querySelectorAll(".tab"))
      t.hidden = t.id !== selectedTab;
    if (selectedTab === "projects")
      loadProjects().catch((e) => message(e.message, true));
    if (selectedTab === "runs")
      loadJobs().catch((e) => message(e.message, true));
  };
$("#provider-form").onsubmit = (e) => {
  e.preventDefault();
  perform(e.submitter, async () => {
    const d = formData(e.target);
    await api("/provider", "PUT", {
      provider: {
        protocol: "openai-compatible",
        base_url: d.endpoint,
        model: d.model,
      },
      ...(d.key ? { api_key: d.key } : {}),
    });
    fill(e.target, "key", "");
    message("Connection saved locally. No provider request was made.");
    await status();
  });
};
$("#test-provider").onclick = (e) =>
  perform(e.target, async () => {
    const form = $("#provider-form");
    const stored = currentStatus.config.provider;
    if (
      form.elements.namedItem("endpoint").value !== stored.base_url ||
      form.elements.namedItem("model").value !== stored.model ||
      form.elements.namedItem("key").value
    ) {
      throw new Error(
        "Save the connection before checking access. No request was sent.",
      );
    }

    if (
      !confirm(
        "Send a models-list request directly to the endpoint shown above? Provider request accounting may apply. Save any changes first.",
      )
    )
      return;
    const r = await api("/provider/test", "POST");
    message(
      r.selected_model_listed
        ? "Connection verified; your selected model is listed."
        : `Connection verified, but your model was not listed. ${r.note}`,
    );
  });
$("#profile-form").onsubmit = (e) => {
  e.preventDefault();
  perform(e.submitter, async () => {
    const d = formData(e.target);
    await api("/profile", "PUT", {
      profile: {
        name: d.name,
        skills: d.skills
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean),
        background: d.background,
        minimum_net_hourly: Number(d.rate),
        maximum_amount: Number(d.amount),
        maximum_hours: Number(d.hours),
      },
      daily_model_tasks: Number(d.daily),
    });
    message(
      "Working profile saved. Existing assessments remain tied to their original context.",
    );
    await status();
  });
};
$("#license-form").onsubmit = (e) => {
  e.preventDefault();
  perform(e.submitter, async () => {
    let doc;
    try {
      doc = JSON.parse(formData(e.target).document);
    } catch {
      throw new Error("Paste a signed JSON document, not a private key.");
    }
    await api("/documents", "POST", { document: doc });
    fill(e.target, "document", "");
    message("Signed document verified and saved.");
    await status();
  });
};
$("#update-form").onsubmit = (e) => {
  e.preventDefault();
  perform(e.submitter, async () => {
    let document;
    try {
      document = JSON.parse(formData(e.target).document);
    } catch {
      throw new Error("Paste signed release JSON.");
    }
    const r = await api("/updates/verify", "POST", { document });
    if (
      !confirm(
        `Download verified version ${r.version} (${Math.ceil(r.bytes / 1048576)} MB)? Nothing will be installed automatically.`,
      )
    )
      return;
    const d = await api("/updates/download", "POST", { document });
    message(`Saved ${d.file}. ${d.next_step}`);
  });
};
$("#account-form").onsubmit = (e) => {
  e.preventDefault();
  perform(e.submitter, async () => {
    const d = formData(e.target);
    await api("/account", "PUT", {
      account_id: Number(d.account),
      ...(d.token ? { token: d.token } : {}),
    });
    fill(e.target, "token", "");
    message("Account configuration saved. No platform request was made.");
    await status();
  });
};
$("#clear-provider").onclick = (e) =>
  perform(e.target, async () => {
    if (
      !confirm(
        "Remove the saved model key? Projects and prior results will be kept.",
      )
    )
      return;
    await api("/provider", "DELETE");
    message("Model key removed from the OS credential vault.");
    await status();
  });
$("#disconnect-account").onclick = (e) =>
  perform(e.target, async () => {
    if (
      !confirm(
        "Remove the saved platform token? Historical submission records will be preserved. Stop the worker first.",
      )
    )
      return;
    await api("/account", "DELETE");
    message(
      "Platform token removed. Submission and unknown-result records were preserved.",
    );
    await status();
  });
$("#pause").onclick = (e) =>
  perform(e.target, async () => {
    await api("/queue", "POST", { paused: !currentStatus.config.queue_paused });
    await status();
    message(
      currentStatus.config.queue_paused
        ? "Queue paused. Current work will finish safely."
        : "Queue resumed. Queued tasks may now use your model API.",
    );
  });
$("#quit").onclick = (e) =>
  perform(e.target, async () => {
    if (
      !confirm(
        "Pause new work and quit after the current task and platform receipt finish?",
      )
    )
      return;
    await api("/shutdown", "POST");
    message(
      "Finishing current work before exit. Reopen BidMaster to reconnect.",
    );
  });
$("#start-platform").onclick = (e) =>
  perform(e.target, async () => {
    if (!$("#platform-consent").checked)
      throw new Error(
        "Confirm your account and model usage authorization first.",
      );
    await api("/automation/start", "POST", {
      mode: $("#platform-mode").value,
      confirm_model_costs: true,
    });
    message(
      "Worker start requested. Check activity and permissions before relying on execution.",
    );
    await status();
  });
$("#stop-platform").onclick = (e) =>
  perform(e.target, async () => {
    await api("/automation/stop", "POST");
    message(
      "Stop requested. Current work and receipt processing will finish before the worker exits.",
    );
    await status();
  });
function download(value, name, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([value], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$("#diagnostics").onclick = (e) =>
  perform(e.target, async () =>
    download(
      JSON.stringify(await api("/diagnostics"), null, 2),
      "bidmaster-diagnostics.json",
    ),
  );
$("#backup").onclick = (e) =>
  perform(e.target, async () => {
    const r = await api("/backup", "POST");
    message(`Backup saved locally: ${r.filename}. ${r.note}`);
  });
$("#open-import").onclick = () => {
  const f = $("#import-form");
  f.reset();
  delete f.dataset.project;
  f.querySelector("button").textContent = "Save project";
  f.hidden = false;
  f.querySelector("input").focus();
};
$("#close-import").onclick = () => ($("#import-form").hidden = true);
$("#import-form").onsubmit = (e) => {
  e.preventDefault();
  perform(e.submitter, async () => {
    const d = formData(e.target);
    await api(
      e.target.dataset.project
        ? `/projects/${e.target.dataset.project}`
        : "/projects",
      e.target.dataset.project ? "PUT" : "POST",
      {
        title: d.title,
        description: d.description,
        budget_minimum: Number(d.minimum),
        budget_maximum: Number(d.maximum),
      },
    );
    e.target.reset();
    e.target.hidden = true;
    message(
      "Project saved locally. Analyze the current brief before generating a new proposal. No model or platform request was made.",
    );
    await loadProjects();
  });
};
function node(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
async function enqueue(id, action, button) {
  await perform(button, async () => {
    if (
      !confirm(
        "Send this brief and your profile directly to your configured model provider? Usage fees apply, and quality checks may use bounded additional requests.",
      )
    )
      return;
    await api(`/projects/${id}/tasks`, "POST", {
      action,
      confirm_model_costs: true,
    });
    message("Task queued. View Activity for its result.");
    await status();
  });
}
async function loadProjects() {
  const list = await api("/projects");
  $("#empty-projects").hidden = list.length > 0;
  const root = $("#project-list");
  root.replaceChildren();
  for (const p of list) {
    const card = node("article", undefined, "panel");
    card.append(node("h3", p.title), node("p", p.description));
    const metrics = node("div", undefined, "metrics");
    for (const [label, value] of [
      ["Assessment", p.score === null ? "Not assessed" : `${p.score}/10`],
      ["Whole scope", p.hours ? `${p.hours} hours` : "Unknown"],
      ["Suggested quote", p.quote_usd ? `$${p.quote_usd}` : "Unknown"],
      [
        "Estimated net/hour",
        p.net_hourly ? `$${p.net_hourly.toFixed(2)}` : "Unknown",
      ],
    ]) {
      const m = node("div", label);
      m.append(node("strong", value));
      metrics.append(m);
    }
    card.append(metrics);
    if (p.explanation) card.append(node("p", p.explanation));
    if (p.questions.length)
      card.append(
        node(
          "p",
          `Scope needs clarification: ${p.questions.join(" · ")}`,
          "error-text",
        ),
      );
    const actions = node("div", undefined, "actions");
    for (const [label, action] of [
      ["Analyze project", "analyze"],
      ["Generate proposal", "proposal"],
    ]) {
      const b = node("button", label, action === "proposal" ? "secondary" : "");
      if (
        action === "proposal" &&
        (p.score === null ||
          p.questions.length ||
          p.recommendation === "reject")
      ) {
        b.disabled = true;
        b.title =
          "Analyze this brief and resolve its assessment concerns first.";
      }
      b.onclick = () => enqueue(p.id, action, b);
      actions.append(b);
    }
    if (p.id < 0) {
      const edit = node("button", "Edit brief", "quiet");
      edit.onclick = () => {
        const f = $("#import-form");
        f.dataset.project = p.id;
        fill(f, "title", p.title);
        fill(f, "description", p.description);
        fill(f, "minimum", p.budget_minimum);
        fill(f, "maximum", p.budget_maximum);
        f.querySelector("button").textContent = "Save changes";
        f.hidden = false;
        f.scrollIntoView({ block: "start", behavior: "auto" });
      };
      actions.append(edit);
    }
    card.append(
      actions,
      node(
        "p",
        "Economic figures are estimates for a fixed-price Freelancer project, not guaranteed earnings. Platform fees and project scope may change.",
        "hint",
      ),
    );
    if (p.proposal) {
      const detail = node("details");
      detail.append(
        node("summary", "Read validated proposal"),
        node("div", p.proposal, "proposal"),
      );
      const copy = node("button", "Copy proposal", "secondary");
      copy.onclick = () =>
        perform(copy, async () => {
          await navigator.clipboard.writeText(p.proposal);
          message("Proposal copied. Review it before submitting.");
        });
      const exp = node("button", "Export proposal", "secondary");
      exp.onclick = () =>
        perform(exp, async () =>
          download(p.proposal, "bidmaster-proposal.txt", "text/plain"),
        );
      const buttons = node("div", undefined, "actions");
      buttons.append(copy, exp);
      detail.append(buttons);
      card.append(detail);
    }
    root.append(card);
  }
}
async function loadJobs() {
  const jobs = await api("/jobs");
  const root = $("#job-list");
  root.replaceChildren();
  if (!jobs.length)
    root.append(
      node(
        "p",
        "No tasks yet. Add a project, then choose Analyze project.",
        "empty",
      ),
    );
  for (const j of jobs) {
    const card = node("article", undefined, "panel");
    card.append(
      node("span", j.state, `badge ${j.state}`),
      node(
        "h3",
        j.action === "analyze" ? "Project assessment" : "Proposal generation",
      ),
      node("p", new Date(j.created_at).toLocaleString(), "job-meta"),
    );
    if (j.error) card.append(node("p", j.error, "error-text"));
    if (j.state === "queued") {
      const b = node("button", "Cancel queued task", "secondary");
      b.onclick = () =>
        perform(b, async () => {
          await api(`/jobs/${j.id}/cancel`, "POST");
          await loadJobs();
        });
      card.append(b);
    }
    root.append(card);
  }
}
$("#refresh").onclick = (e) => perform(e.target, loadJobs);
if (!session) {
  $("#welcome").hidden = false;
  $("#connection").textContent = "Launcher session required";
} else {
  status(true).catch((e) => message(e.message, true));
  setInterval(() => {
    status().catch(() => {
      $("#connection").textContent = "Local instance disconnected";
      $("#connection").classList.remove("ready");
    });
    if (selectedTab === "runs") loadJobs().catch(() => {});
  }, 4000);
}
