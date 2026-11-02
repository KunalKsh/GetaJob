// GetaJob front end: CSRF-aware fetch, refresh progress, tracker autosave, uploads, copy links.
(function () {
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  const post = (url, body) => fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: Object.assign({"X-CSRF-Token": csrf}, body ? {"Content-Type": "application/json"} : {}),
    body: body ? JSON.stringify(body) : undefined
  });
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

  // ---- refresh (admin button) and progress for everyone
  const btn = document.getElementById("refresh-btn");
  const status = document.getElementById("refresh-status");
  let polling = null;
  function poll() {
    fetch("/api/refresh/status", {credentials: "same-origin"}).then(r => r.ok ? r.json() : null).then(d => {
      if (!d || !status) return;
      if (d.state.running) {
        status.innerHTML = '<span class="spinner"></span> Updating jobs: ' + esc(d.state.phase || "") + " " + esc(d.state.detail || "");
      } else {
        clearInterval(polling); polling = null;
        if (btn) btn.disabled = false;
        status.textContent = d.state.error ? d.state.error : "Jobs updated just now";
        if (!d.state.error) setTimeout(() => location.reload(), 800);
      }
    }).catch(() => {});
  }
  if (btn) {
    btn.addEventListener("click", () => {
      btn.disabled = true;
      post("/api/refresh").then(r => r.json()).then(() => { if (!polling) polling = setInterval(poll, 2500); })
        .catch(() => { status.textContent = "Couldn't reach the server."; btn.disabled = false; });
    });
  }
  if (status && status.querySelector(".spinner") && !polling) polling = setInterval(poll, 2500);

  // ---- tracker fields save on change
  document.addEventListener("change", e => {
    const el = e.target.closest("[data-track]");
    if (!el || (!el.value && el.dataset.field === "status")) return;
    const body = {}; body[el.dataset.field] = el.value;
    post("/api/tracker/" + encodeURIComponent(el.dataset.track), body).then(r => {
      el.style.outline = r.ok ? "2px solid var(--green)" : "2px solid var(--red)";
      setTimeout(() => (el.style.outline = ""), 900);
    });
  });

  // ---- written fit summary, copy buttons, confirmations
  document.addEventListener("click", e => {
    const s = e.target.closest("[data-summary]");
    if (s) {
      s.disabled = true; s.textContent = "Writing…";
      post("/api/jobs/" + encodeURIComponent(s.dataset.summary) + "/summary").then(async r => {
        const d = await r.json();
        const out = document.querySelector('[data-summary-out="' + s.dataset.summary + '"]');
        if (r.ok) { out.textContent = d.summary; s.remove(); }
        else { out.textContent = d.detail || "Couldn't write a summary."; s.disabled = false; s.textContent = "Try again"; }
      });
    }
    const c = e.target.closest("[data-copy]");
    if (c) {
      const input = document.getElementById(c.dataset.copy);
      const done = () => { c.textContent = "Copied"; setTimeout(() => (c.textContent = "Copy link"), 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(input.value).then(done, () => { input.select(); });
      else { input.select(); document.execCommand("copy"); done(); }
    }
  });
  document.addEventListener("submit", e => {
    const msg = e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // ---- resume drop zone
  const dz = document.getElementById("dropzone");
  if (dz) {
    const input = dz.querySelector('input[type="file"]');
    const list = document.getElementById("filelist");
    const show = () => { list.textContent = Array.from(input.files).map(f => f.name + " (" + Math.round(f.size / 1024) + " KB)").join(", "); };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
    dz.addEventListener("drop", e => { if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); } });
  }
})();
