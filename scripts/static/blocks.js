// Drag-and-drop block editor for input/resume.json and input/section_order.yaml.
//
// Works on the same in-memory file contents as the raw editor tabs
// (state.files in templates/editor.html): every edit here re-serializes the
// parsed resume back into state.files["resume.json"], so switching to the raw
// tab always shows the current blocks, and vice versa. Fields show LaTeX with
// single backslashes (e.g. $\cdot$); JSON escaping only happens on serialize.
// Unknown keys in resume.json are preserved, since edits mutate the parsed
// objects in place.
"use strict";

const Blocks = (() => {
  const RESUME = "resume.json";
  const ORDER = "section_order.yaml";
  const SECTIONS = JSON.parse(document.querySelector("#config").textContent).sections;
  // Headings as generate_resume.py prints them.
  const LABELS = {
    summary: "Professional Summary",
    competencies: "Core Competencies",
    experience: "Professional Experience",
    early_career: "Early Career",
    education: "Education",
    certifications: "Selected Certifications",
    recognition: "Recognition & Speaking",
    projects: "Selected Independent Projects",
  };
  const TEXT_SECTIONS = new Set(["summary", "early_career", "certifications"]);
  // Sections that are lists of two-field entries ({name|title, description}).
  const ENTRY_SECTIONS = {
    competencies: ["name", "description"],
    recognition: ["title", "description"],
    projects: ["title", "description"],
  };
  const UNDO_LIMIT = 50;
  const NATIVE_AUTOSIZE = Boolean(window.CSS && CSS.supports("field-sizing", "content"));

  const root = document.querySelector("#blocks");
  const body = document.querySelector("#blocksBody");
  const undoBtn = document.querySelector("#blocksUndo");

  let model = null; // parsed resume.json
  let order = []; // section_order.yaml's list
  let orderHeader = []; // section_order.yaml's leading comment lines
  let parsedFrom = { resume: null, order: null }; // file text model/order came from
  let undoStack = [];
  const closedSections = new Set();
  const openEmployers = new WeakSet();

  // --- helpers --------------------------------------------------------------

  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (typeof value === "function") el.addEventListener(key.slice(2), value);
      else if (value === true) el.setAttribute(key, "");
      else if (value !== false && value != null) el.setAttribute(key, value);
    }
    el.append(...children.flat().filter((c) => c != null && c !== false));
    return el;
  }

  function autosize(el) {
    if (NATIVE_AUTOSIZE || !el.offsetParent) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }

  function autosizeWithin(container) {
    container.querySelectorAll("textarea").forEach(autosize);
  }

  // A button inside a <summary> would otherwise also toggle its <details>.
  function button(label, onClick, attrs = {}) {
    return h("button", { type: "button", ...attrs, onclick: (e) => { e.preventDefault(); e.stopPropagation(); onClick(); } }, label);
  }

  const handle = () => h("span", { class: "handle", title: "Drag to reorder", "aria-hidden": "true" }, "⠿");

  // --- section_order.yaml ------------------------------------------------------

  function parseOrder(text) {
    const header = [];
    const sections = [];
    for (const raw of text.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith("#")) {
        if (!sections.length) header.push(raw);
        continue;
      }
      const match = /^-\s+(\w+)$/.exec(line);
      if (!match) throw new Error(`${ORDER}: can't read line "${raw}"`);
      sections.push(match[1]);
    }
    return { header, sections };
  }

  function serializeOrder() {
    return [...orderHeader, ...order.map((s) => `- ${s}`)].join("\n") + "\n";
  }

  // --- state <-> files -------------------------------------------------------

  // Re-parses the files only if they changed since this editor last
  // produced them (e.g. after editing the raw resume.json tab or a reload),
  // so expanded/collapsed state survives switching tabs.
  function open() {
    const resumeText = state.files[RESUME];
    const orderText = state.files[ORDER];
    if (model && resumeText === parsedFrom.resume && orderText === parsedFrom.order) {
      render();
      return;
    }
    try {
      const parsed = JSON.parse(resumeText);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("expected a JSON object");
      const parsedOrder = parseOrder(orderText);
      model = parsed;
      order = parsedOrder.sections;
      orderHeader = parsedOrder.header.length ? parsedOrder.header : ["# Top-level keys from resume.json, in the order they appear in the resume."];
      parsedFrom = { resume: resumeText, order: orderText };
      undoStack = [];
      render();
    } catch (error) {
      model = null;
      body.replaceChildren(
        h("div", { class: "blocks-error" },
          h("p", {}, `The block editor can't open this resume: ${error.message}`),
          h("p", {}, "Fix it in the raw ", button(RESUME, () => selectFile(RESUME), { class: "link" }), " tab first."))
      );
    }
  }

  // Forget the parsed model so the next open() re-reads state.files.
  function reset() {
    model = null;
    parsedFrom = { resume: null, order: null };
  }

  // Writes the model back into state.files after any edit.
  function commit() {
    const resumeText = JSON.stringify(model, null, 2);
    const orderText = state.files[ORDER] === parsedFrom.order && sameOrder() ? state.files[ORDER] : serializeOrder();
    state.files[RESUME] = resumeText;
    state.files[ORDER] = orderText;
    parsedFrom = { resume: resumeText, order: orderText };
    renderTabs();
  }

  // Avoids rewriting section_order.yaml (dropping any interleaved comments)
  // when only resume.json changed.
  function sameOrder() {
    try {
      return parseOrder(parsedFrom.order).sections.join() === order.join();
    } catch {
      return false;
    }
  }

  // Structural edits (add/delete/move) are undoable and re-render the blocks;
  // plain typing isn't (the field's own Ctrl+Z covers that).
  function change(mutate) {
    undoStack.push({ resume: state.files[RESUME], order: state.files[ORDER] });
    if (undoStack.length > UNDO_LIMIT) undoStack.shift();
    mutate();
    commit();
    render();
  }

  // Restoring a snapshot re-parses it into new objects, so which employers
  // were expanded is carried over by position.
  function undo() {
    const snapshot = undoStack.pop();
    if (!snapshot) return;
    const stack = undoStack;
    const employers = () => (Array.isArray(model.experience) ? model.experience : []);
    const openIndexes = employers().flatMap((e, i) => (openEmployers.has(e) ? [i] : []));
    state.files[RESUME] = snapshot.resume;
    state.files[ORDER] = snapshot.order;
    reset();
    open();
    for (const i of openIndexes) if (employers()[i]) openEmployers.add(employers()[i]);
    render();
    undoStack = stack;
    undoBtn.disabled = !undoStack.length;
    renderTabs();
  }

  // --- fields ----------------------------------------------------------------

  // An input (or auto-growing textarea, with multiline) bound to obj[key].
  // optional: the key is only created once it's non-empty, so untouched
  // optional fields (like stack) don't appear in resume.json as "".
  function field(obj, key, { label, multiline = false, required = false, optional = false, hint, onInput } = {}) {
    const hadKey = key in obj;
    const control = multiline ? h("textarea", { rows: 1, spellcheck: "true" }) : h("input", { type: "text", spellcheck: "true" });
    control.value = obj[key] ?? "";
    if (required) control.dataset.required = "";
    control.addEventListener("input", () => {
      if (optional && !hadKey && control.value === "") delete obj[key];
      else obj[key] = control.value;
      control.classList.remove("invalid");
      autosize(control);
      commit();
      if (onInput) onInput();
    });
    return h("label", { class: `field${multiline ? " wide" : ""}` },
      h("span", { class: "label" }, label, required ? h("span", { class: "req" }, " *") : null, hint ? h("span", { class: "hint" }, ` — ${hint}`) : null),
      control);
  }

  // A sortable list of `items`, rendered by renderItem(item, index, items).
  function list(items, group, renderItem, className = "") {
    const el = h("div", { class: `list ${className}` }, items.map((item, i) => renderItem(item, i, items)));
    el._items = items;
    pendingSortables.push({ el, group });
    return el;
  }

  let pendingSortables = [];

  function initSortables() {
    for (const { el, group } of pendingSortables) {
      Sortable.create(el, {
        group,
        handle: ".handle",
        draggable: ".item",
        animation: 150,
        ghostClass: "ghost",
        onEnd(evt) {
          const from = evt.from._items;
          const to = evt.to._items;
          const oldIndex = evt.oldDraggableIndex;
          const newIndex = evt.newDraggableIndex;
          if (from === to && oldIndex === newIndex) return;
          change(() => {
            const [moved] = from.splice(oldIndex, 1);
            to.splice(newIndex, 0, moved);
          });
        },
      });
    }
    pendingSortables = [];
  }

  function itemTools(items, index, { duplicate = true } = {}) {
    return h("span", { class: "tools" },
      duplicate ? button("Duplicate", () => change(() => items.splice(index + 1, 0, structuredClone(items[index]))), { title: "Duplicate" }) : null,
      button("Delete", () => change(() => items.splice(index, 1)), { class: "danger", title: "Delete" }));
  }

  // --- section order card ---------------------------------------------------------

  function renderOrderCard() {
    const excluded = SECTIONS.filter((s) => !order.includes(s));
    const chip = (key) => h("div", { class: "item chip", "data-key": key }, handle(), LABELS[key] || key);
    const included = h("div", { class: "chips" }, order.map(chip));
    const hidden = h("div", { class: "chips excluded" }, excluded.map(chip));
    for (const el of [included, hidden]) {
      Sortable.create(el, {
        group: "section-order",
        draggable: ".item",
        animation: 150,
        ghostClass: "ghost",
        onEnd() {
          const next = [...included.children].map((c) => c.dataset.key);
          if (next.join() === order.join()) return;
          change(() => {
            order = next;
            for (const key of order) if (!(key in model)) model[key] = TEXT_SECTIONS.has(key) ? "" : [];
          });
        },
      });
    }
    return h("section", { class: "block order-card" },
      h("h3", {}, "Sections"),
      h("p", { class: "hint" }, "Drag to reorder. Drag a section to the second row to leave it out of the resume (its content is kept)."),
      included,
      hidden);
  }

  // --- sections -----------------------------------------------------------------

  function renderSection(key) {
    const included = order.includes(key);
    const details = h("details", { class: `block section${included ? "" : " excluded"}`, open: !closedSections.has(key) },
      h("summary", {}, LABELS[key] || key, included ? null : h("span", { class: "tag" }, "not in resume")),
      renderSectionBody(key));
    details.addEventListener("toggle", () => {
      if (details.open) closedSections.delete(key);
      else closedSections.add(key);
      autosizeWithin(details);
    });
    return details;
  }

  function renderSectionBody(key) {
    const value = model[key];
    if (TEXT_SECTIONS.has(key) && typeof value === "string") {
      return field(model, key, { label: "Text", multiline: true });
    }
    if (key === "experience" && Array.isArray(value)) return renderExperience(value);
    if (key === "education" && Array.isArray(value)) return renderEducation(value);
    if (ENTRY_SECTIONS[key] && Array.isArray(value)) return renderEntries(key, value);
    return h("p", { class: "hint" }, `Edit "${key}" in the raw ${RESUME} tab.`);
  }

  function renderEntries(key, items) {
    const [titleKey, descKey] = ENTRY_SECTIONS[key];
    const blank = () => ({ [titleKey]: "", [descKey]: "" });
    const required = key === "competencies"; // generate_resume.py's validate()
    return h("div", {},
      list(items, key, (item, i) => h("div", { class: "item entry" },
        handle(),
        h("div", { class: "fields" },
          field(item, titleKey, { label: titleKey === "name" ? "Name" : "Title", required }),
          field(item, descKey, { label: "Description", multiline: true, required })),
        itemTools(items, i))),
      button(`+ Add ${key === "competencies" ? "competency" : "entry"}`, () => change(() => items.push(blank())), { class: "add" }));
  }

  function renderEducation(items) {
    return h("div", {},
      list(items, "education", (item, i) => h("div", { class: "item entry" },
        handle(),
        h("div", { class: "fields row3" },
          field(item, "degree", { label: "Degree" }),
          field(item, "institution", { label: "Institution" }),
          field(item, "year", { label: "Year" })),
        itemTools(items, i))),
      button("+ Add education", () => change(() => items.push({ degree: "", institution: "", year: "" })), { class: "add" }));
  }

  function renderExperience(employers) {
    return h("div", {},
      list(employers, "employers", (employer, i) => renderEmployer(employer, i, employers)),
      button("+ Add employer", () => change(() => {
        const employer = { employer: "", location: "", dates: "", roles: [newRole()] };
        employers.unshift(employer);
        openEmployers.add(employer);
      }), { class: "add" }));
  }

  const newRole = () => ({ title: "", dates: "", duties: [""] });

  function renderEmployer(employer, index, employers) {
    const roles = Array.isArray(employer.roles) ? employer.roles : (employer.roles = []);
    const title = h("span", { class: "title" });
    const updateTitle = () => {
      const roleCount = `${roles.length} role${roles.length === 1 ? "" : "s"}`;
      title.textContent = [employer.employer || "(new employer)", employer.dates, roleCount].filter(Boolean).join(" · ");
    };
    updateTitle();
    const details = h("details", { class: "item employer", open: openEmployers.has(employer) },
      h("summary", {}, handle(), title, itemTools(employers, index)),
      h("div", { class: "fields row3" },
        field(employer, "employer", { label: "Employer", required: true, onInput: updateTitle }),
        field(employer, "location", { label: "Location" }),
        field(employer, "dates", { label: "Dates", onInput: updateTitle })),
      h("div", { class: "fields" },
        field(employer, "stack", { label: "Stack", optional: true, hint: "printed once, after all roles" })),
      list(roles, "roles", (role, i) => renderRole(role, i, roles, employer), "roles"),
      button("+ Add role", () => change(() => roles.push(newRole())), { class: "add" }));
    details.addEventListener("toggle", () => {
      if (details.open) openEmployers.add(employer);
      else openEmployers.delete(employer);
      autosizeWithin(details);
    });
    return details;
  }

  function renderRole(role, index, roles, employer) {
    const duties = Array.isArray(role.duties) ? role.duties : (role.duties = []);
    const pagebreak = h("input", { type: "checkbox", checked: Boolean(role.pagebreak_before) });
    pagebreak.addEventListener("change", () => {
      if (pagebreak.checked) role.pagebreak_before = true;
      else delete role.pagebreak_before;
      commit();
    });
    const multiRole = (employer.roles || []).length > 1;
    return h("div", { class: "item role" },
      h("div", { class: "role-head" },
        handle(),
        h("strong", {}, "Role"),
        h("label", { class: "check" }, pagebreak, "Start on a new page"),
        itemTools(roles, index)),
      h("div", { class: "fields row2" },
        field(role, "title", { label: "Title", required: true }),
        field(role, "dates", { label: "Dates", hint: multiRole ? null : "only printed when the employer has several roles" })),
      h("div", { class: "label" }, "Duties", h("span", { class: "req" }, " *")),
      list(duties, "duties", (duty, i) => {
        const text = h("textarea", { rows: 1, spellcheck: "true", "data-required": true });
        text.value = duty;
        text.addEventListener("input", () => {
          duties[i] = text.value;
          text.classList.remove("invalid");
          autosize(text);
          commit();
        });
        return h("div", { class: "item duty" }, handle(), text, button("✕", () => change(() => duties.splice(i, 1)), { class: "danger icon", title: "Delete duty" }));
      }, "duties"),
      button("+ Add duty", () => change(() => duties.push("")), { class: "add" }),
      h("div", { class: "fields" }, field(role, "stack", { label: "Stack", optional: true, hint: "printed under this role" })));
  }

  // --- render / validate / save ---------------------------------------------------

  function render() {
    if (!model) return;
    const scroll = window.scrollY;
    const shown = [...order, ...SECTIONS.filter((s) => !order.includes(s) && s in model)];
    for (const key of Object.keys(model)) if (!shown.includes(key)) shown.push(key);
    body.replaceChildren(renderOrderCard(), ...shown.map(renderSection));
    initSortables();
    autosizeWithin(body);
    window.scrollTo(0, scroll);
    undoBtn.disabled = !undoStack.length;
  }

  // Mirrors generate_resume.py's validate(), so a save here never produces a
  // resume.json that `make build` would reject -- plus blank duties, which it
  // would happily print as empty bullets.
  function validate() {
    const problems = [];
    for (const key of order) if (!(key in model)) problems.push(`${LABELS[key] || key} is in the section order but has no content.`);
    (Array.isArray(model.competencies) ? model.competencies : []).forEach((c, i) => {
      if (!c.name || !c.description) problems.push(`Core Competencies #${i + 1} needs a name and description.`);
    });
    (Array.isArray(model.experience) ? model.experience : []).forEach((employer, i) => {
      const where = employer.employer || `employer #${i + 1}`;
      if (!employer.employer) problems.push(`Experience ${where}: employer name is required.`);
      (employer.roles || []).forEach((role, j) => {
        const roleName = role.title || `role #${j + 1}`;
        if (!role.title) problems.push(`Experience ${where} › ${roleName}: title is required.`);
        if (!role.duties || !role.duties.length) problems.push(`Experience ${where} › ${roleName}: add at least one duty.`);
        if ((role.duties || []).some((d) => !String(d).trim())) problems.push(`Experience ${where} › ${roleName}: fill in or delete the blank duty.`);
      });
    });
    // Highlight empty required fields, opening anything collapsed around them.
    root.querySelectorAll("[data-required]").forEach((el) => {
      const empty = !el.value.trim();
      el.classList.toggle("invalid", empty);
      if (empty) for (let d = el.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
    });
    return problems;
  }

  async function save() {
    if (!model) return false;
    const problems = validate();
    if (problems.length) {
      report(`Not saved — ${problems.length} problem${problems.length === 1 ? "" : "s"}: ${problems.join(" ")}`, "error");
      return false;
    }
    const changed = [RESUME, ORDER].filter((name) => state.files[name] !== state.saved[name]);
    if (!changed.length) {
      report("No changes to save.");
      return true;
    }
    try {
      for (const name of changed) {
        const content = state.files[name];
        await request("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, content }) });
        state.saved[name] = content;
      }
      renderTabs();
      report(`Saved ${changed.map((name) => `input/${name}`).join(" and ")}.`, "ok");
      return true;
    } catch (error) {
      report(error.message, "error");
      return false;
    }
  }

  function setAllOpen(open) {
    root.querySelectorAll("details.employer").forEach((d) => (d.open = open));
    root.querySelectorAll("details.section").forEach((d) => (d.open = open));
  }

  document.querySelector("#blocksSave").addEventListener("click", save);
  document.querySelector("#blocksBuild").addEventListener("click", async () => {
    if (await save()) run("build");
  });
  undoBtn.addEventListener("click", undo);
  document.querySelector("#blocksExpand").addEventListener("click", () => setAllOpen(true));
  document.querySelector("#blocksCollapse").addEventListener("click", () => setAllOpen(false));

  return { open, reset };
})();
