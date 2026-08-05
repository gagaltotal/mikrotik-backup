// ── Theme toggle ─────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.classList.toggle("dark");
  localStorage.setItem("theme", isDark ? "dark" : "light");
}

// ── Sidebar ──────────────────────────────────────────────────
function toggleSidebar() {
  const sb = document.getElementById("sidebar");
  const ov = document.getElementById("sidebar-overlay");
  sb.classList.toggle("-translate-x-full");
  ov.classList.toggle("hidden");
}

// ── User menu ────────────────────────────────────────────────
function toggleUserMenu() {
  document.getElementById("user-dropdown").classList.toggle("hidden");
}
document.addEventListener("click", (e) => {
  const menu = document.getElementById("user-menu");
  if (menu && !menu.contains(e.target)) {
    document.getElementById("user-dropdown").classList.add("hidden");
  }
});

document.addEventListener("click", (e) => {
  const button = e.target.closest("button[data-action]");
  if (!button) return;

  const action = button.dataset.action;
  if (!action) return;

  if (action === "test") {
    const routerId = button.dataset.routerId;
    if (!routerId) return;
    testRouter(routerId);
  } else if (action === "backup") {
    const routerId = button.dataset.routerId;
    if (!routerId) return;
    runBackup(routerId, button.dataset.backupType);
  } else if (action === "toggle-schedule") {
    const scheduleId = button.dataset.scheduleId;
    if (!scheduleId) return;
    toggleSchedule(scheduleId, button);
  } else if (action === "toggle-sidebar") {
    toggleSidebar();
  } else if (action === "toggle-theme") {
    toggleTheme();
  } else if (action === "toggle-user-menu") {
    toggleUserMenu();
  }
});

document.addEventListener("click", (e) => {
  if (e.target.id === "sidebar-overlay") {
    toggleSidebar();
  }
});

document.addEventListener("submit", (e) => {
  const form = e.target.closest("form[data-confirm]");
  if (!form) return;

  const message = form.dataset.confirm;
  if (!message) return;

  if (!confirm(message)) {
    e.preventDefault();
  }
});

// ── CSRF helper ──────────────────────────────────────────────
function getCSRF() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

// ── API call helper ──────────────────────────────────────────
async function api(url, opts = {}) {
  opts.headers = opts.headers || {};
  opts.headers["X-CSRF-Token"] = getCSRF();
  if (opts.body && typeof opts.body === "object") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, opts);
  return res.json();
}

function showAlert(message, icon = "info", title = "") {
  if (typeof Swal !== "undefined" && Swal.fire) {
    Swal.fire({
      title: title || (icon === "success" ? "Success" : icon === "error" ? "Error" : ""),
      text: message,
      icon: icon,
      confirmButtonText: "OK",
    });
  } else {
    console.warn("Swal not loaded; falling back to alert.");
    alert((title ? title + ": " : "") + message);
  }
}

function showError(message) {
  showAlert(message, "error", "Error");
}

function showSuccess(message, title = "Success") {
  showAlert(message, "success", title);
}

// ── Test router connection ───────────────────────────────────
async function testRouter(rid) {
  if (!confirm("Test connection to this router?")) return;
  const card = document.querySelector(`[data-router-id="${rid}"]`);
  const badge = card?.querySelector(".status-badge");
  if (badge) {
    badge.textContent = "testing";
    badge.className =
      "status-badge bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 animate-pulse";
  }
  try {
    const r = await api(`/api/routers/${rid}/test`, { method: "POST" });
    if (r.success) {
      showSuccess(r.message || "Connection successful.", "Connection tested");
    } else {
      showError(r.message || "Connection failed.");
    }
  } catch (e) {
    showError("Error: " + e);
  }
}

// ── Trigger backup ───────────────────────────────────────────
async function runBackup(rid, type) {
  if (!confirm(`Run ${type} backup now?`)) return;
  try {
    const r = await api(`/api/routers/${rid}/backup`, {
      method: "POST",
      body: { backup_type: type },
    });
    if (r.success) {
      showSuccess(`Backup started. Watch the status badge for updates.`, `${type} Backup`);
    } else {
      showError(r.message || "Backup failed.");
    }
  } catch (e) {
    showError("Error: " + e);
  }
}

// ── Toggle schedule ──────────────────────────────────────────
async function toggleSchedule(sid, btn) {
  try {
    const r = await api(`/api/schedules/${sid}/toggle`, { method: "POST" });
    if (r.success) {
      btn.classList.toggle("on", r.enabled);
    }
  } catch (e) {
    showError("Error: " + e);
  }
}

// ── SSE real-time status ─────────────────────────────────────
if (
  typeof EventSource !== "undefined" &&
  document.querySelector(".router-card")
) {
  const es = new EventSource("/api/events");
  es.addEventListener("status", (e) => {
    try {
      const data = JSON.parse(e.data);
      const card = document.querySelector(
        `[data-router-id="${data.router_id}"]`,
      );
      if (!card) return;
      const badge = card.querySelector(".status-badge");
      if (badge) {
        badge.textContent = data.status;
        badge.className = "status-badge " + getStatusClass(data.status);
      }
    } catch (err) {}
  });
  es.onerror = () => {
    /* will auto-reconnect */
  };
}

function getStatusClass(s) {
  const map = {
    online:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    offline: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300",
    error: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    backup_running:
      "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 animate-pulse",
    backup_success:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    backup_failed:
      "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
  };
  return (
    map[s] || "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
  );
}

// ── Auto-refresh dashboard stats every 30s ───────────────────
if (document.querySelector(".router-card")) {
  setInterval(async () => {
    try {
      const r = await fetch("/api/routers/status");
      const data = await r.json();
      (data.routers || []).forEach((router) => {
        const card = document.querySelector(`[data-router-id="${router.id}"]`);
        if (!card) return;
        const badge = card.querySelector(".status-badge");
        if (badge && !badge.classList.contains("animate-pulse")) {
          badge.textContent = router.last_status || "unknown";
          badge.className =
            "status-badge " + getStatusClass(router.last_status);
        }
      });
    } catch (e) {}
  }, 30000);
}
