// DIANE Frontend (API-backed)
// Endpoints:
// GET  /api/items?search=&kinds=&include_archived=&include_reviewed=
// POST /api/items
// PATCH /api/items/:id   { reviewed, archived, title?, content?, kind? }
// POST /api/items/bulk   { ids, action }

const API_BASE = "https://diane.onrender.com";


const state = {
  items: [],
  filtered: [],
  kinds: ["DEV_TICKET","BUSINESS_TODO","CUSTOMER_SUPPORT","DEMO_PREP","CRM_ACTION","NOTE"],
  activeKinds: new Set(),
  includeArchived: false,
  includeReviewed: true,
  search: "",
  selectedIndex: 0,
  useDemoData: false,
};

const el = (id) => document.getElementById(id);

function nowISO() {
  return new Date().toISOString();
}

function demoItems() {
  return [
    {
      id: crypto.randomUUID(),
      kind: "DEV_TICKET",
      title: "Voice Agent triggert Pitch nicht",
      content:
        "diane gitlab voice agent pitch bug workspace switch\nRepro: nur wenn Funktion direkt im Devtool gecallt wird.",
      source: "telegram_voice",
      created_at: nowISO(),
      reviewed: false,
      archived: false,
    },
    {
      id: crypto.randomUUID(),
      kind: "DEMO_PREP",
      title: "Agenda: Sales Titans Demo",
      content:
        "diane demo agenda sales titans\nFokus: Onboarding Story, Playbooks, keine Feature-Tour.",
      source: "telegram_text",
      created_at: nowISO(),
      reviewed: true,
      archived: false,
    },
    {
      id: crypto.randomUUID(),
      kind: "CRM_ACTION",
      title: "Neuer Kontakt: Tuukka Teppola (Valuelab)",
      content:
        "diane crm new contact tuukka teppola valuelab\nNotiz: interessiert an Playbooks.",
      source: "telegram_text",
      created_at: nowISO(),
      reviewed: false,
      archived: false,
    },
    {
      id: crypto.randomUUID(),
      kind: "BUSINESS_TODO",
      title: "Follow-up Hörer & Flamme",
      content:
        "diane followup hörer flamme januar\nkurz update + 2 optionen für next steps.",
      source: "telegram_voice",
      created_at: nowISO(),
      reviewed: false,
      archived: false,
    },
    {
      id: crypto.randomUUID(),
      kind: "NOTE",
      title: "Idee: DIANE als Capture OS",
      content:
        "diane: sticky-notes inbox, weekly review, export lanes (gitlab, crm, demo, mail).",
      source: "telegram_text",
      created_at: nowISO(),
      reviewed: true,
      archived: true,
    },
  ];
}

// ---------- API adapter ----------
async function apiGetItems() {
  const params = new URLSearchParams();
  if (state.search.trim()) params.set("search", state.search.trim());
  if (state.activeKinds.size)
    params.set("kinds", Array.from(state.activeKinds).join(","));
  params.set("include_archived", String(state.includeArchived));
  params.set("include_reviewed", String(state.includeReviewed));

  const res = await fetch(`${API_BASE}/api/items?${params.toString()}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "GET /api/items failed");
  return data.items || [];
}

async function apiCreateItem({ kind, content }) {
  const res = await fetch(`${API_BASE}/api/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind,
      content,
      source: "web_quicknote",
    }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "POST /api/items failed");
  return data.item;
}

async function apiPatchItem(id, patch) {
  const res = await fetch(`${API_BASE}/api/items/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "PATCH /api/items failed");
  return data.item;
}

async function apiBulk(ids, action) {
  const res = await fetch(`${API_BASE}/api/items/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, action }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "POST /api/items/bulk failed");
  return data.updated || 0;
}

// ---------- Data loading ----------
async function fetchItems() {
  if (state.useDemoData) return demoItems();
  return await apiGetItems();
}

async function createItem({ kind, content }) {
  await apiCreateItem({ kind, content });
  state.items = await fetchItems();
  applyFiltersAndRender();
}

async function patchItem(id, patch) {
  await apiPatchItem(id, patch);
  state.items = await fetchItems();
  applyFiltersAndRender(true);
}

async function bulkAction(ids, action) {
  await apiBulk(ids, action);
  state.items = await fetchItems();
  applyFiltersAndRender(true);
}

async function apiDeleteItem(id) {
  // Backend erlaubt DELETE nicht -> Soft delete via PATCH
  const item = await apiPatchItem(id, { archived: true, reviewed: true });
  return { deleted: false, item };
}

async function deleteItem(id) {
  await apiDeleteItem(id);
  state.items = await fetchItems();
  applyFiltersAndRender(true);
}


// ---------- UI ----------
function deriveTitle(kind, content) {
  const line = (content || "").trim().split("\n")[0]?.slice(0, 90) || "Untitled";
  return (
    line.replace(/^diane\s+/i, "").replace(/^#\w+\s+/i, "") || `${kind}: ${line}`
  );
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function mountKindFilters() {
  const wrap = el("kindFilters");
  wrap.innerHTML = "";
  state.kinds.forEach((kind) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.textContent = kind;
    chip.onclick = async () => {
      if (state.activeKinds.has(kind)) state.activeKinds.delete(kind);
      else state.activeKinds.add(kind);

      // Reload from API with kinds filter (so backend can filter too)
      state.items = await fetchItems();
      applyFiltersAndRender();
      mountKindFilters();
    };
    if (state.activeKinds.has(kind)) chip.classList.add("active");
    wrap.appendChild(chip);
  });
}

function matchesSearch(item, q) {
  if (!q) return true;
  const hay = `${item.title}\n${item.content}\n${item.kind}\n${item.source}`.toLowerCase();
  const parts = q.toLowerCase().split(/\s+/).filter(Boolean);
  return parts.every((p) => hay.includes(p));
}

function applyFiltersAndRender(keepSelection = false) {
  const q = state.search.trim();

  // We still filter client-side as a safety net.
  // Primary filtering is already in the backend query.
  state.filtered = state.items
    .filter((it) => (state.includeArchived ? true : !it.archived))
    .filter((it) => (state.includeReviewed ? true : !it.reviewed))
    .filter((it) =>
      state.activeKinds.size ? state.activeKinds.has(it.kind) : true
    )
    .filter((it) => matchesSearch(it, q));

  if (!keepSelection) state.selectedIndex = 0;
  if (state.selectedIndex >= state.filtered.length)
    state.selectedIndex = Math.max(0, state.filtered.length - 1);

  render();
}

function render() {
  const board = el("board") || el("grid");
  const empty = el("emptyState");
  const stats = el("stats");

  const total = state.items.length;
  const open = state.items.filter(x => !x.archived).length;
  const unreviewed = state.items.filter(x => !x.reviewed && !x.archived).length;

  stats.textContent = `${state.filtered.length} shown · ${unreviewed} unreviewed · ${open} open · ${total} total`;

  board.innerHTML = "";
  if (state.filtered.length === 0) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  // group by kind
  const byKind = new Map();
  state.kinds.forEach(k => byKind.set(k, []));
  state.filtered.forEach(it => {
    if (!byKind.has(it.kind)) byKind.set(it.kind, []);
    byKind.get(it.kind).push(it);
  });

  const orderedKinds = [
    ...state.kinds,
    ...Array.from(byKind.keys()).filter(k => !state.kinds.includes(k))
  ];

  orderedKinds.forEach(kind => {
    const items = byKind.get(kind) || [];
    if (items.length === 0) return;

    const col = document.createElement("div");
    col.className = "column";

    const head = document.createElement("div");
    head.className = "col-head";

    const title = document.createElement("div");
    title.className = "col-title";
    title.innerHTML = `<span class="kind">${kind}</span><span class="col-pill">${items.length}</span>`;

    head.appendChild(title);
    col.appendChild(head);

    // 🔽 DROP TARGET (HIER IST DER PUNKT)
    const list = document.createElement("div");
    list.className = "col-list";
    list.dataset.kind = kind;

    list.addEventListener("dragover", (e) => {
      e.preventDefault();
      list.classList.add("drag-over");
    });

    list.addEventListener("dragleave", () => {
      list.classList.remove("drag-over");
    });

    list.addEventListener("drop", async (e) => {
      e.preventDefault();
      list.classList.remove("drag-over");

      const id = e.dataTransfer.getData("text/plain");
      if (!id) return;

      await patchItem(id, { kind });
    });

    // cards
    items.forEach(it => {
      const card = renderCard(it);
      list.appendChild(card);
    });

    col.appendChild(list);
    board.appendChild(col);
  });
}

function renderCard(it) {
  const card = document.createElement("div");
  card.className = "card";
  // full-card color by kind
  const kindClass =
    it.kind === "DEV_TICKET" ? "card-dev" :
    it.kind === "CRM_ACTION" ? "card-crm" :
    it.kind === "DEMO_PREP" ? "card-demo" :
    it.kind === "BUSINESS_TODO" ? "card-business" :
    "card-note";

  card.classList.add(kindClass);

  card.draggable = true;
  card.dataset.id = it.id;
  card.dataset.kind = it.kind;

  card.addEventListener("dragstart", (e) => {
  e.dataTransfer.setData("text/plain", it.id);
  card.classList.add("dragging");
  });

  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
  });

  const top = document.createElement("div");
  top.className = "card-top";

  const kind = document.createElement("div");
  kind.className = "kind";
  kind.textContent = it.kind;

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML = `<span class="dot"></span><span>${formatTime(it.created_at)}</span><span>·</span><span>${it.source || "—"}</span>`;

  top.appendChild(kind);
  top.appendChild(meta);

  const title = document.createElement("div");
  title.className = "title";
  title.textContent = it.title || deriveTitle(it.kind, it.content);

  const body = document.createElement("div");
  body.className = "body";
  body.textContent = it.content || "";

  const actions = document.createElement("div");
  actions.className = "card-actions";

  const btnReview = document.createElement("button");
  btnReview.className = "btn btn-small";
  btnReview.textContent = it.reviewed ? "Reviewed ✓" : "Mark Reviewed";
  btnReview.onclick = async (e) => {
    e.stopPropagation();
    await patchItem(it.id, { reviewed: true });
  };

  const btnArchive = document.createElement("button");
  btnArchive.className = "btn btn-small btn-ghost";
  btnArchive.textContent = it.archived ? "Archived ✓" : "Archive";
  btnArchive.onclick = async (e) => {
    e.stopPropagation();
    await patchItem(it.id, { archived: true });
  };

  const btnCopy = document.createElement("button");
  btnCopy.className = "btn btn-small btn-ghost";
  btnCopy.textContent = "Copy";
  btnCopy.onclick = async (e) => {
    e.stopPropagation();
    await navigator.clipboard.writeText(`${it.kind}: ${it.title}\n\n${it.content}`);
    btnCopy.textContent = "Copied";
    setTimeout(() => (btnCopy.textContent = "Copy"), 900);
  };

  const btnDelete = document.createElement("button");
  btnDelete.className = "btn btn-small btn-ghost";
  btnDelete.textContent = "Delete";
  btnDelete.onclick = async (e) => {
    e.stopPropagation();

    const ok = confirm("Wirklich löschen? (Fallback: archived+reviewed)");
    if (!ok) return;

    await deleteItem(it.id);
  };

  actions.appendChild(btnReview);
  actions.appendChild(btnArchive);
  actions.appendChild(btnCopy);
  actions.appendChild(btnDelete);

  // verhindern, dass drag/click komisch wird
  [btnReview, btnArchive, btnCopy, btnDelete].forEach(btn => {
    btn.addEventListener("mousedown", (e) => e.stopPropagation());
  });

  const badges = document.createElement("div");
  badges.style.marginTop = "10px";
  badges.style.display = "flex";
  badges.style.gap = "8px";
  badges.style.flexWrap = "wrap";
  if (!it.reviewed) badges.appendChild(makeBadge("unreviewed"));
  if (it.archived) badges.appendChild(makeBadge("archived"));

  card.appendChild(top);
  card.appendChild(title);
  card.appendChild(body);
  if (badges.childNodes.length) card.appendChild(badges);
  card.appendChild(actions);

  return card;
}


function makeBadge(text) {
  const b = document.createElement("div");
  b.className = "badge";
  b.dataset.state = text; // "unreviewed" | "archived" | "reviewed"
  b.innerHTML = `<span class="dot"></span><span>${text}</span>`;
  return b;
}

// ---------- Keyboard UX ----------
function bindKeyboard() {
  document.addEventListener("keydown", (e) => {
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";
    if (typing) {
      if (e.key === "Escape") document.activeElement.blur();
      return;
    }

    if (e.key === "/") {
      e.preventDefault();
      el("searchInput").focus();
      return;
    }
    if (e.key === "j") {
      state.selectedIndex = Math.min(state.filtered.length - 1, state.selectedIndex + 1);
      render();
      return;
    }
    if (e.key === "k") {
      state.selectedIndex = Math.max(0, state.selectedIndex - 1);
      render();
      return;
    }
    if (e.key === "r") {
      const it = state.filtered[state.selectedIndex];
      if (it) patchItem(it.id, { reviewed: true });
      return;
    }
    if (e.key === "a") {
      const it = state.filtered[state.selectedIndex];
      if (it) patchItem(it.id, { archived: true });
      return;
    }
  });
}

// ---------- Modal ----------
function openModal() {
  el("modal").classList.remove("hidden");
  el("modalText").value = "";
  el("modalKind").value = "NOTE";
  el("modalText").focus();
}
function closeModal() {
  el("modal").classList.add("hidden");
}

// ---------- Init ----------
async function init() {
  mountKindFilters();
  bindKeyboard();

  el("searchInput").addEventListener("input", async (e) => {
    state.search = e.target.value;
    // For real API search, reload from backend as you type:
    state.items = await fetchItems();
    applyFiltersAndRender();
  });

  el("toggleArchived").addEventListener("change", async (e) => {
    state.includeArchived = e.target.checked;
    state.items = await fetchItems();
    applyFiltersAndRender();
  });

  el("toggleReviewed").addEventListener("change", async (e) => {
    state.includeReviewed = e.target.checked;
    state.items = await fetchItems();
    applyFiltersAndRender();
  });

  el("btnRefresh").onclick = async () => {
    state.items = await fetchItems();
    applyFiltersAndRender();
  };

  el("btnDemoData").onclick = async () => {
    state.useDemoData = true;
    state.items = await fetchItems();
    applyFiltersAndRender();
  };

  el("btnCreateLocal").onclick = () => openModal();
  el("modalClose").onclick = () => closeModal();
  el("modal").onclick = (e) => {
    if (e.target === el("modal")) closeModal();
  };

  el("modalSave").onclick = async () => {
    const content = el("modalText").value.trim();
    const kind = el("modalKind").value;
    if (!content) return;
    await createItem({ kind, content });
    closeModal();
  };

  el("btnBulkReview").onclick = async () => {
    const ids = state.filtered.map((x) => x.id);
    await bulkAction(ids, "review");
  };

  el("btnBulkArchive").onclick = async () => {
    const ids = state.filtered.map((x) => x.id);
    await bulkAction(ids, "archive");
  };

  // initial load from API
  state.items = await fetchItems();
  applyFiltersAndRender();
}

init();
