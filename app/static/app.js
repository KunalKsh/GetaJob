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

  // ---- preferences wizard
  const wz = document.getElementById("wizard");
  if (wz) {
    wz.classList.add("js");
    const steps = 4;
    const famBoxes = () => Array.from(wz.querySelectorAll('input[name="families"]'));
    const chosenFams = () => famBoxes().filter(b => b.checked).map(b => b.value);
    let loadedFams = chosenFams().join(",");
    const go = (n, quiet) => {
      n = Math.max(1, Math.min(steps, n));
      if (n > 1 && !chosenFams().length) { note(1, "Pick at least one kind of job to continue."); n = 1; }
      wz.dataset.step = n;
      if (n === 2 && chosenFams().join(",") !== loadedFams) loadRoles();
      if (n === 3) filterCompanies();
      if (!quiet) window.scrollTo({top: wz.offsetTop - 70, behavior: "smooth"});
    };
    const note = (step, text) => {
      const sec = wz.querySelector('.step[data-step="' + step + '"]');
      let n = sec.querySelector(".stepnote");
      if (!n) { n = document.createElement("div"); n.className = "notice warn stepnote"; sec.prepend(n); }
      n.textContent = text;
    };
    wz.querySelectorAll("[data-goto]").forEach(b => b.addEventListener("click", () => go(+b.dataset.goto)));
    wz.querySelector("[data-next]").addEventListener("click", () => go(+wz.dataset.step + 1));
    wz.querySelector("[data-prev]").addEventListener("click", () => go(+wz.dataset.step - 1));
    wz.addEventListener("submit", e => {
      if (!wz.querySelector('input[name="roles"]:checked') && !wz.querySelector("#custom_roles").value.trim()) {
        e.preventDefault(); go(2); note(2, "Tick at least one role, or type one in the box below.");
      } else if (!wz.querySelector('input[name="primary_cities"]:checked')) {
        e.preventDefault(); go(4); note(4, "Choose at least one first-choice city.");
      }
    });

    const list = document.getElementById("role-list");
    function loadRoles() {
      const fams = chosenFams();
      const before = loadedFams.split(",");
      const prev = new Set(Array.from(list.querySelectorAll('input[name="roles"]:checked')).map(i => i.value));
      list.classList.add("loading");
      const qs = fams.map(f => "f=" + encodeURIComponent(f)).join("&");
      fetch("/api/roles?" + qs, {credentials: "same-origin"}).then(r => r.json()).then(d => {
        const seen = new Set();
        let html = "";
        d.roles.forEach(r => {
          seen.add(r.title);
          const on = prev.has(r.title) || (!before.includes(r.family) && r.score >= 75);
          html += '<label class="rolerow"><input type="checkbox" name="roles" value="' + esc(r.title) + '"' + (on ? " checked" : "") + '>' +
            '<span class="rr-main"><b>' + esc(r.title) + '</b><span class="small muted">' + esc(r.reason) + '</span></span>' +
            '<span class="rr-fam small">' + esc(r.family_name) + '</span>' +
            '<span class="rr-score"><span class="mono">' + r.score + '</span><span class="meter"><i style="width:' + Math.min(100, r.score) + '%"></i></span></span></label>';
        });
        prev.forEach(t => { if (!seen.has(t)) html += '<label class="rolerow"><input type="checkbox" name="roles" value="' + esc(t) + '" checked><span class="rr-main"><b>' + esc(t) + '</b><span class="small muted">Kept from your earlier choice</span></span><span></span><span></span></label>'; });
        list.innerHTML = html || '<div class="empty">No suggestions. Type the roles you want below.</div>';
        loadedFams = fams.join(",");
      }).catch(() => {}).finally(() => list.classList.remove("loading"));
    }
    wz.querySelectorAll("[data-roles]").forEach(b => b.addEventListener("click", () => {
      list.querySelectorAll('input[name="roles"]').forEach(i => (i.checked = b.dataset.roles === "all"));
    }));

    const coBox = document.getElementById("pref_co");
    const added = () => new Set(coBox.value.split(/\n|,/).map(x => x.trim().toLowerCase()).filter(Boolean));
    function filterCompanies() {
      const fams = new Set(chosenFams()), have = added();
      let shown = 0;
      wz.querySelectorAll("[data-add-company]").forEach(c => {
        const on = fams.has(c.dataset.family) && !have.has(c.dataset.addCompany.toLowerCase()) && shown < 40;
        c.hidden = !on; if (on) shown++;
      });
    }
    wz.addEventListener("click", e => {
      const c = e.target.closest("[data-add-company]");
      if (!c) return;
      const v = coBox.value.replace(/\s+$/, "");
      coBox.value = (v ? v + "\n" : "") + c.dataset.addCompany;
      filterCompanies();
    });
    coBox.addEventListener("input", filterCompanies);
    wz.addEventListener("change", e => {
      const t = e.target;
      if (t.dataset && t.dataset.cityGroup && t.checked) {
        const other = t.dataset.cityGroup === "p" ? "secondary_cities" : "primary_cities";
        const twin = wz.querySelector('input[name="' + other + '"][value="' + CSS.escape(t.value) + '"]');
        if (twin) twin.checked = false;
      }
    });
    filterCompanies();
    go(+wz.dataset.step || 1, true);
  }

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
