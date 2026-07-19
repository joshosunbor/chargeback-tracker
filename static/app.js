const STATUSES = ["new", "under_review", "represented", "won", "lost", "accepted"];
const view = document.getElementById("view");
const userBox = document.getElementById("userBox");

let currentUser = null;

// ---------- helpers ----------

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    // Session expired or not logged in: send the user to the login screen
    currentUser = null;
    renderUserBox();
    renderLogin();
    throw new Error(body.error || "authentication required");
  }
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const money = (cents, currency) =>
  (cents / 100).toLocaleString(undefined, { style: "currency", currency: currency || "USD" });

const badge = (status) => `<span class="badge ${esc(status)}">${esc(status.replace("_", " "))}</span>`;

const statusOptions = (selected) =>
  STATUSES.map((s) => `<option value="${s}" ${s === selected ? "selected" : ""}>${s.replace("_", " ")}</option>`).join("");

function showError(err) {
  const div = document.createElement("div");
  div.className = "error";
  div.textContent = err.message || String(err);
  view.prepend(div);
  setTimeout(() => div.remove(), 5000);
}

// ---------- auth ----------

function renderUserBox() {
  if (!currentUser) {
    userBox.innerHTML = "";
    return;
  }
  userBox.innerHTML = `<span>${esc(currentUser.username)}</span><button id="logoutBtn">Log out</button>`;
  document.getElementById("logoutBtn").onclick = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    currentUser = null;
    renderUserBox();
    renderLogin();
  };
}

let signupOpen = false;  // set at boot from /api/auth/config

function renderLogin(mode = "login") {
  // Never show the register form when signup is closed, even if asked.
  const isLogin = mode === "login" || !signupOpen;
  view.innerHTML = `
    <div class="card auth-card">
      <h2>${isLogin ? "Log in" : "Create account"}</h2>
      <div id="authError"></div>
      <form id="authForm">
        <div class="field"><label>Username</label><input name="username" required autofocus></div>
        <div class="field"><label>Password</label><input name="password" type="password" required minlength="4"></div>
        <button type="submit">${isLogin ? "Log in" : "Create account"}</button>
      </form>
      ${!signupOpen ? "" : `<p class="switch">${isLogin
        ? `No account yet? <a id="switchMode">Create one</a>`
        : `Already have an account? <a id="switchMode">Log in</a>`}</p>`}
    </div>
  `;
  const switchLink = document.getElementById("switchMode");
  if (switchLink) switchLink.onclick = () => renderLogin(isLogin ? "register" : "login");
  document.getElementById("authForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      currentUser = await api(`/api/auth/${isLogin ? "login" : "register"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: f.get("username").trim(), password: f.get("password") }),
      });
      renderUserBox();
      location.hash = "#/";
      route();
    } catch (err) {
      document.getElementById("authError").innerHTML = `<div class="error">${esc(err.message)}</div>`;
    }
  };
}

// ---------- list view ----------

async function renderList() {
  const params = new URLSearchParams();
  const status = renderList.status || "";
  const q = renderList.q || "";
  if (status) params.set("status", status);
  if (q) params.set("q", q);

  const cases = await api(`/api/cases?${params}`);

  view.innerHTML = `
    <div class="toolbar">
      <input id="search" type="search" placeholder="Search case #, merchant, customer…" value="${esc(q)}">
      <select id="statusFilter">
        <option value="">All statuses</option>
        ${statusOptions(status)}
      </select>
      <div class="spacer"></div>
      <button id="newCase">+ New case</button>
    </div>
    ${cases.length === 0 ? `<p class="empty">No cases found.</p>` : `
    <table>
      <thead><tr><th>Case #</th><th>Merchant</th><th>Customer</th><th>Amount</th><th>Reason</th><th>Status</th><th>Due</th></tr></thead>
      <tbody>
        ${cases.map((c) => `
          <tr data-id="${c.id}">
            <td>${esc(c.case_number)}</td>
            <td>${esc(c.merchant)}</td>
            <td>${esc(c.customer)}</td>
            <td>${money(c.amount_cents, c.currency)}</td>
            <td>${esc(c.reason_code)}</td>
            <td>${badge(c.status)}</td>
            <td>${esc(c.due_date)}</td>
          </tr>`).join("")}
      </tbody>
    </table>`}
  `;

  document.getElementById("newCase").onclick = () => { location.hash = "#/new"; };
  document.getElementById("statusFilter").onchange = (e) => { renderList.status = e.target.value; renderList().catch(showError); };
  document.getElementById("search").oninput = (e) => {
    clearTimeout(renderList.timer);
    renderList.timer = setTimeout(() => { renderList.q = e.target.value; renderList().catch(showError); }, 250);
  };
  view.querySelectorAll("tbody tr").forEach((tr) => {
    tr.onclick = () => { location.hash = `#/case/${tr.dataset.id}`; };
  });
}

// ---------- new case form ----------

function renderNew() {
  view.innerHTML = `
    <div class="card">
      <h2>New case</h2>
      <form id="caseForm">
        <div class="grid">
          <div class="field"><label>Case number *</label><input name="case_number" required></div>
          <div class="field"><label>Merchant *</label><input name="merchant" required></div>
          <div class="field"><label>Customer</label><input name="customer"></div>
          <div class="field"><label>Amount *</label><input name="amount" type="number" step="0.01" min="0" required></div>
          <div class="field"><label>Currency</label><input name="currency" value="USD" maxlength="3"></div>
          <div class="field"><label>Reason code</label><input name="reason_code"></div>
          <div class="field"><label>Received</label><input name="received_date" type="date"></div>
          <div class="field"><label>Due</label><input name="due_date" type="date"></div>
        </div>
        <p><button type="submit">Create</button> <button type="button" class="secondary" id="cancel">Cancel</button></p>
      </form>
    </div>
  `;
  document.getElementById("cancel").onclick = () => { location.hash = "#/"; };
  document.getElementById("caseForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const payload = {
      case_number: f.get("case_number").trim(),
      merchant: f.get("merchant").trim(),
      customer: f.get("customer").trim() || null,
      amount_cents: Math.round(parseFloat(f.get("amount")) * 100),
      currency: f.get("currency").trim().toUpperCase() || "USD",
      reason_code: f.get("reason_code").trim() || null,
      received_date: f.get("received_date") || null,
      due_date: f.get("due_date") || null,
    };
    try {
      const created = await api("/api/cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      location.hash = `#/case/${created.id}`;
    } catch (err) { showError(err); }
  };
}

// ---------- detail view ----------

async function renderDetail(id) {
  const c = await api(`/api/cases/${id}`);

  view.innerHTML = `
    <div class="card">
      <div class="row" style="justify-content: space-between">
        <h2 style="margin:0">${esc(c.case_number)} ${badge(c.status)}</h2>
        <button class="danger" id="deleteCase">Delete</button>
      </div>
      <div class="grid" style="margin-top:1rem">
        <div class="field"><label>Merchant</label><div>${esc(c.merchant)}</div></div>
        <div class="field"><label>Customer</label><div>${esc(c.customer) || "—"}</div></div>
        <div class="field"><label>Amount</label><div>${money(c.amount_cents, c.currency)}</div></div>
        <div class="field"><label>Reason code</label><div>${esc(c.reason_code) || "—"}</div></div>
        <div class="field"><label>Received</label><div>${esc(c.received_date) || "—"}</div></div>
        <div class="field"><label>Due</label><div>${esc(c.due_date) || "—"}</div></div>
        <div class="field"><label>Resolved</label><div>${esc(c.resolved_date) || "—"}</div></div>
      </div>
      <div class="row" style="margin-top:1rem">
        <div class="field"><label>Change status</label>
          <select id="statusSelect">${statusOptions(c.status)}</select>
        </div>
        <input id="statusNote" placeholder="Optional note for the audit log" style="flex:1;padding:0.4rem 0.6rem;border:1px solid #cbd2dc;border-radius:6px;align-self:flex-end">
        <button id="applyStatus" style="align-self:flex-end">Apply</button>
      </div>
    </div>

    <div class="card">
      <h3>History</h3>
      <ul class="timeline">
        ${c.history.map((h) => `
          <li>${h.old_status ? `${badge(h.old_status)} → ` : ""}${badge(h.new_status)}
              ${h.note ? ` — ${esc(h.note)}` : ""}
              <span class="muted">${h.username ? `by ${esc(h.username)} · ` : ""}${esc(h.created_at)}</span></li>`).join("")}
      </ul>
    </div>

    <div class="card">
      <h3>Notes</h3>
      ${c.notes.length === 0 ? `<p class="empty">No notes yet.</p>` : `
      <ul class="plain">
        ${c.notes.map((n) => `<li>${esc(n.body)} <span class="muted">${n.username ? `— ${esc(n.username)} · ` : ""}${esc(n.created_at)}</span></li>`).join("")}
      </ul>`}
      <div class="row" style="margin-top:0.75rem">
        <textarea id="noteBody" rows="2" placeholder="Add a note…"></textarea>
        <button id="addNote">Add</button>
      </div>
    </div>

    <div class="card">
      <h3>Attachments</h3>
      ${c.attachments.length === 0 ? `<p class="empty">No attachments.</p>` : `
      <ul class="plain">
        ${c.attachments.map((a) => `
          <li class="row" style="justify-content: space-between">
            <span><a href="/api/attachments/${a.id}">${esc(a.filename)}</a>
              <span class="muted">${(a.size_bytes / 1024).toFixed(1)} KB · ${a.username ? `${esc(a.username)} · ` : ""}${esc(a.created_at)}</span></span>
            <button class="secondary" data-del-attachment="${a.id}">Remove</button>
          </li>`).join("")}
      </ul>`}
      <div class="row" style="margin-top:0.75rem">
        <input type="file" id="fileInput">
        <button id="uploadBtn">Upload</button>
      </div>
    </div>
  `;

  const reload = () => renderDetail(id).catch(showError);

  document.getElementById("applyStatus").onclick = async () => {
    const status = document.getElementById("statusSelect").value;
    const note = document.getElementById("statusNote").value.trim();
    try {
      await api(`/api/cases/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, status_note: note || null }),
      });
      reload();
    } catch (err) { showError(err); }
  };

  document.getElementById("deleteCase").onclick = async () => {
    if (!confirm(`Delete case ${c.case_number}? This removes its history, notes, and attachments.`)) return;
    try {
      await api(`/api/cases/${id}`, { method: "DELETE" });
      location.hash = "#/";
    } catch (err) { showError(err); }
  };

  document.getElementById("addNote").onclick = async () => {
    const body = document.getElementById("noteBody").value.trim();
    if (!body) return;
    try {
      await api(`/api/cases/${id}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      reload();
    } catch (err) { showError(err); }
  };

  document.getElementById("uploadBtn").onclick = async () => {
    const input = document.getElementById("fileInput");
    if (!input.files.length) return;
    const form = new FormData();
    form.append("file", input.files[0]);
    try {
      await api(`/api/cases/${id}/attachments`, { method: "POST", body: form });
      reload();
    } catch (err) { showError(err); }
  };

  view.querySelectorAll("[data-del-attachment]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/attachments/${btn.dataset.delAttachment}`, { method: "DELETE" });
        reload();
      } catch (err) { showError(err); }
    };
  });
}

// ---------- router ----------

function route() {
  if (!currentUser) return renderLogin();
  const hash = location.hash || "#/";
  const caseMatch = hash.match(/^#\/case\/(\d+)$/);
  if (hash === "#/new") return renderNew();
  if (caseMatch) return renderDetail(caseMatch[1]).catch(showError);
  return renderList().catch(showError);
}

window.addEventListener("hashchange", route);

// Boot: restore the session if the cookie is still valid, else show login
(async () => {
  try {
    const cfg = await api("/api/auth/config");
    signupOpen = !!cfg.signup_open;
  } catch {
    signupOpen = false;
  }
  try {
    currentUser = await api("/api/auth/me");
  } catch {
    currentUser = null;
  }
  renderUserBox();
  route();
})();
