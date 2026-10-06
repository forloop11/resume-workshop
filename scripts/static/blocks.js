// Drag-and-drop block editor for input/resume.json (a JSON Resume document,
// https://jsonresume.org/schema) and input/section_order.yaml.
//
// Works on the same in-memory file contents as the raw editor tabs
// (state.files in templates/editor.html): every edit here re-serializes the
// document back into state.files["resume.json"], so switching to the raw tab
// always shows the current blocks, and vice versa. Text is plain Unicode
// (&, %, ·, –); scripts/generate_resume.py escapes it for LaTeX.
//
// JSON Resume stores one work[] entry per position. Like the generator
// (scripts/jsonresume.py's experience_groups), this editor shows consecutive
// entries with the same employer name and location as one employer card, and
// writes the card's name/location back onto each of its roles. Entries
// flagged earlyCareer get their own Early Career card instead. Unknown keys
// are preserved, since edits mutate the parsed objects in place.
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
  // The top-level JSON Resume array each list section edits.
  const LIST_KEYS = { competencies: "skills", education: "education", certifications: "certificates", recognition: "awards", projects: "projects" };
  // The JSON Resume iso8601 definition: YYYY, YYYY-MM, or YYYY-MM-DD.
  const ISO8601 = /^([1-2][0-9]{3}-[0-1][0-9]-[0-3][0-9]|[1-2][0-9]{3}-[0-1][0-9]|[1-2][0-9]{3})$/;
  const UNDO_LIMIT = 50;
  const NATIVE_AUTOSIZE = Boolean(window.CSS && CSS.supports("field-sizing", "content"));

  const root = document.querySelector("#blocks");
  const body = document.querySelector("#blocksBody");
  const undoBtn = document.querySelector("#blocksUndo");

  let model = null; // the parsed JSON Resume document
  let groups = []; // experience: [{ name, location, companyStack, roles: [work entries] }]
  let early = []; // work entries with earlyCareer: true
  let order = []; // section_order.yaml's list
  let orderHeader = []; // section_order.yaml's leading comment lines
  let parsedFrom = { resume: null, order: null }; // file text model/order came from
  let undoStack = [];
  let lastField = null; // most recently focused field, for the · and – buttons
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
  const list = (value) => (Array.isArray(value) ? value : []);

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

  // --- work[] <-> employer groups ----------------------------------------------

  function groupWork(work) {
    const result = [];
    const earlyEntries = [];
    for (const entry of list(work)) {
      if (entry.earlyCareer) {
        earlyEntries.push(entry);
        continue;
      }
      const last = result[result.length - 1];
      if (last && last.name === (entry.name || "") && last.location === (entry.location || "")) {
        last.roles.push(entry);
      } else {
        result.push({ name: entry.name || "", location: entry.location || "", companyStack: "", roles: [entry] });
      }
    }
    for (const group of result) group.companyStack = group.roles.map((r) => r.companyStack).find(Boolean) || "";
    return { groups: result, early: earlyEntries };
  }

  // Writes the employer cards back as flat work[] entries: each role gets its
  // card's name/location, and companyStack lives on the first role only.
  function flattenWork() {
    const work = [];
    for (const group of groups) {
      group.roles.forEach((role, i) => {
        role.name = group.name;
        if (group.location) role.location = group.location;
        else delete role.location;
        // Assign only on change, so existing keys keep their position in the file.
        const companyStack = i === 0 ? group.companyStack : "";
        if (!companyStack) delete role.companyStack;
        else if (role.companyStack !== companyStack) role.companyStack = companyStack;
        delete role.earlyCareer;
        work.push(role);
      });
    }
    for (const entry of early) {
      entry.earlyCareer = true;
      work.push(entry);
    }
    return work;
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
      if (!model.basics || typeof model.basics !== "object") model.basics = {};
      ({ groups, early } = groupWork(model.work));
      order = parsedOrder.sections;
      orderHeader = parsedOrder.header.length ? parsedOrder.header : ["# Resume sections, in the order they appear. Omit one to leave it out."];
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
    model.work = flattenWork();
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
    const openIndexes = groups.flatMap((g, i) => (openEmployers.has(g) ? [i] : []));
    state.files[RESUME] = snapshot.resume;
    state.files[ORDER] = snapshot.order;
    reset();
    open();
    for (const i of openIndexes) if (groups[i]) openEmployers.add(groups[i]);
    render();
    undoStack = stack;
    undoBtn.disabled = !undoStack.length;
    renderTabs();
  }

  // --- fields ----------------------------------------------------------------

  // An input (or auto-growing textarea, with multiline) bound to obj[key].
  // An emptied field removes its key, as JSON Resume documents usually omit
  // unused fields -- except required ones, which stay as "".
  // date: validated as YYYY / YYYY-MM / YYYY-MM-DD.
  function field(obj, key, { label, multiline = false, required = false, date = false, placeholder, hint, onInput } = {}) {
    const control = multiline ? h("textarea", { rows: 1, spellcheck: "true" }) : h("input", { type: "text", spellcheck: date ? "false" : "true" });
    control.value = obj[key] ?? "";
    if (placeholder || date) control.placeholder = placeholder || "YYYY-MM";
    if (required) control.dataset.required = "";
    if (date) control.dataset.date = "";
    control.addEventListener("input", () => {
      if (control.value === "" && !required) delete obj[key];
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

  // A textarea editing obj[key], an array of strings, one item per line.
  function linesField(obj, key, { label, hint, required = false } = {}) {
    const control = h("textarea", { rows: 2, spellcheck: "true" });
    control.value = list(obj[key]).join("\n");
    if (required) control.dataset.required = "";
    control.addEventListener("input", () => {
      obj[key] = control.value.split("\n").map((line) => line.trim()).filter(Boolean);
      control.classList.remove("invalid");
      autosize(control);
      commit();
    });
    return h("label", { class: "field wide" },
      h("span", { class: "label" }, label, required ? h("span", { class: "req" }, " *") : null, hint ? h("span", { class: "hint" }, ` — ${hint}`) : null),
      control);
  }

  let pendingSortables = [];

  // forceFallback: Sortable's own mouse-driven drag instead of native HTML5
  // drag-and-drop, which Chromium won't start for large items full of inputs
  // (a whole role card); fallbackOnBody keeps the drag image above nested lists.
  const SORTABLE_OPTIONS = { animation: 150, ghostClass: "ghost", forceFallback: true, fallbackOnBody: true };

  // A sortable list of `items`, rendered by renderItem(item, index, items).
  function sortableList(items, group, renderItem, className = "") {
    const el = h("div", { class: `list ${className}` }, items.map((item, i) => renderItem(item, i, items)));
    el._items = items;
    pendingSortables.push({ el, group });
    return el;
  }

  function initSortables() {
    for (const { el, group } of pendingSortables) {
      Sortable.create(el, {
        ...SORTABLE_OPTIONS,
        group,
        handle: ".handle",
        draggable: ".item",
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

  // A card for a list of simple entries: a drag handle, the fields from
  // renderFields(item), and Duplicate/Delete.
  function entryList(items, group, renderFields, { addLabel, blank, fieldsClass = "" }) {
    return h("div", {},
      sortableList(items, group, (item, i) => h("div", { class: "item entry" },
        handle(),
        h("div", { class: `fields ${fieldsClass}` }, renderFields(item)),
        itemTools(items, i))),
      button(addLabel, () => change(() => items.push(blank())), { class: "add" }));
  }

  // --- header card (basics) ------------------------------------------------------

  function renderBasics() {
    const basics = model.basics;
    if (!basics.location || typeof basics.location !== "object") basics.location = {};
    if (!Array.isArray(basics.profiles)) basics.profiles = [];
    const details = h("details", { class: "block section", open: !closedSections.has("basics") },
      h("summary", {}, "Header", h("span", { class: "tag" }, "basics")),
      h("div", { class: "fields row3" },
        field(basics, "name", { label: "Name", required: true }),
        field(basics, "label", { label: "Title", required: true }),
        field(basics, "email", { label: "Email", required: true })),
      h("div", { class: "fields row3" },
        field(basics, "phone", { label: "Phone", required: true }),
        field(basics.location, "city", { label: "City", required: true }),
        field(basics.location, "region", { label: "Region / state" })),
      h("div", { class: "fields row2" },
        field(basics.location, "countryCode", { label: "Country code", hint: "not printed" }),
        field(basics, "url", { label: "Website", hint: "printed before the profile links" })),
      h("div", { class: "label" }, "Profile links", h("span", { class: "hint" }, " — printed in this order")),
      entryList(basics.profiles, "profiles", (p) => [
        field(p, "network", { label: "Network", placeholder: "LinkedIn" }),
        field(p, "username", { label: "Username", hint: "link text ends here" }),
        field(p, "url", { label: "URL", required: true, placeholder: "https://" }),
      ], { addLabel: "+ Add profile link", blank: () => ({ network: "", url: "" }), fieldsClass: "row-profile" }));
    details.addEventListener("toggle", () => toggleSection(details, "basics"));
    return details;
  }

  // --- section order card ---------------------------------------------------------

  // Gives a section something to edit once it's added to the resume.
  function ensureSectionData(key) {
    if (key === "summary" && typeof model.basics.summary !== "string") model.basics.summary = "";
    if (LIST_KEYS[key] && !Array.isArray(model[LIST_KEYS[key]])) model[LIST_KEYS[key]] = [];
  }

  function hasData(key) {
    if (key === "summary") return typeof model.basics.summary === "string";
    if (key === "experience") return groups.length > 0;
    if (key === "early_career") return early.length > 0;
    return Array.isArray(model[LIST_KEYS[key]]);
  }

  function renderOrderCard() {
    const excluded = SECTIONS.filter((s) => !order.includes(s));
    const chip = (key) => h("div", { class: "item chip", "data-key": key }, handle(), LABELS[key] || key);
    const included = h("div", { class: "chips" }, order.map(chip));
    const hidden = h("div", { class: "chips excluded" }, excluded.map(chip));
    for (const el of [included, hidden]) {
      Sortable.create(el, {
        ...SORTABLE_OPTIONS,
        group: "section-order",
        draggable: ".item",
        onEnd() {
          const next = [...included.children].map((c) => c.dataset.key);
          if (next.join() === order.join()) return;
          change(() => {
            order = next;
            order.forEach(ensureSectionData);
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

  function toggleSection(details, key) {
    if (details.open) closedSections.delete(key);
    else closedSections.add(key);
    autosizeWithin(details);
  }

  function renderSection(key) {
    const included = order.includes(key);
    const details = h("details", { class: `block section${included ? "" : " excluded"}`, open: !closedSections.has(key) },
      h("summary", {}, LABELS[key] || key, included ? null : h("span", { class: "tag" }, "not in resume")),
      renderSectionBody(key));
    details.addEventListener("toggle", () => toggleSection(details, key));
    return details;
  }

  function renderSectionBody(key) {
    switch (key) {
      case "summary":
        return field(model.basics, "summary", { label: "basics.summary", multiline: true, required: included(key) });
      case "experience":
        return renderExperience();
      case "early_career":
        return entryList(early, "early", (e) => [
          h("div", { class: "fields row2" },
            field(e, "position", { label: "Position", required: true }),
            field(e, "name", { label: "Employer(s)", required: true })),
          h("div", { class: "fields row2" },
            field(e, "startDate", { label: "Start", date: true, placeholder: "YYYY" }),
            field(e, "endDate", { label: "End", date: true, placeholder: "YYYY" })),
          field(e, "summary", { label: "Summary", multiline: true, hint: "printed after the dates" }),
        ], { addLabel: "+ Add early career entry", blank: () => ({ name: "", position: "", earlyCareer: true }) });
      case "competencies":
        return entryList(listFor(key), "skills", (s) => [
          field(s, "name", { label: "Name", required: true }),
          linesField(s, "keywords", { label: "Keywords", hint: "one per line, printed separated by ·", required: true }),
        ], { addLabel: "+ Add competency", blank: () => ({ name: "", keywords: [] }) });
      case "education":
        return entryList(listFor(key), "education", (e) => [
          h("div", { class: "fields row2" },
            field(e, "studyType", { label: "Degree type", placeholder: "Bachelor of Science" }),
            field(e, "area", { label: "Area", hint: "printed as “type in area”" })),
          h("div", { class: "fields row2" },
            field(e, "institution", { label: "Institution", required: true }),
            field(e, "endDate", { label: "Year completed", date: true, placeholder: "YYYY" })),
        ], { addLabel: "+ Add education", blank: () => ({ institution: "", studyType: "" }) });
      case "certifications":
        return entryList(listFor(key), "certificates", (c) => [
          h("div", { class: "fields row2" },
            field(c, "name", { label: "Name", required: true }),
            field(c, "issuer", { label: "Issuer", hint: "printed after the name" })),
          h("div", { class: "fields row2" },
            field(c, "date", { label: "Date", date: true, hint: "not printed" }),
            field(c, "url", { label: "URL", hint: "not printed" })),
        ], { addLabel: "+ Add certification", blank: () => ({ name: "" }) });
      case "recognition":
        return entryList(listFor(key), "awards", (a) => [
          field(a, "title", { label: "Title", required: true }),
          field(a, "summary", { label: "Summary", multiline: true }),
          h("div", { class: "fields row2" },
            field(a, "date", { label: "Date", date: true, placeholder: "YYYY", hint: "not printed" }),
            field(a, "awarder", { label: "Awarder", hint: "not printed" })),
        ], { addLabel: "+ Add entry", blank: () => ({ title: "" }) });
      case "projects":
        return entryList(listFor(key), "projects", (p) => [
          field(p, "name", { label: "Name", required: true }),
          field(p, "description", { label: "Description", multiline: true }),
        ], { addLabel: "+ Add project", blank: () => ({ name: "" }) });
      default:
        return h("p", { class: "hint" }, `Edit "${key}" in the raw ${RESUME} tab.`);
    }
  }

  const included = (key) => order.includes(key);

  function listFor(key) {
    ensureSectionData(key);
    return model[LIST_KEYS[key]];
  }

  const newRole = () => ({ name: "", position: "", highlights: [""] });

  function renderExperience() {
    return h("div", {},
      sortableList(groups, "employers", (group, i) => renderEmployer(group, i)),
      button("+ Add employer", () => change(() => {
        const group = { name: "", location: "", companyStack: "", roles: [newRole()] };
        groups.unshift(group);
        openEmployers.add(group);
      }), { class: "add" }));
  }

  function renderEmployer(group, index) {
    const title = h("span", { class: "title" });
    const updateTitle = () => {
      const roleCount = `${group.roles.length} role${group.roles.length === 1 ? "" : "s"}`;
      title.textContent = [group.name || "(new employer)", group.location, roleCount].filter(Boolean).join(" · ");
    };
    updateTitle();
    const details = h("details", { class: "item employer", open: openEmployers.has(group) },
      h("summary", {}, handle(), title, itemTools(groups, index)),
      h("div", { class: "fields row2" },
        field(group, "name", { label: "Employer", required: true, onInput: updateTitle }),
        field(group, "location", { label: "Location", onInput: updateTitle })),
      h("div", { class: "fields" },
        field(group, "companyStack", { label: "Company stack", hint: "printed once, after all roles" })),
      sortableList(group.roles, "roles", (role, i) => renderRole(role, i, group), "roles"),
      button("+ Add role", () => change(() => group.roles.push(newRole())), { class: "add" }));
    details.addEventListener("toggle", () => {
      if (details.open) openEmployers.add(group);
      else openEmployers.delete(group);
      autosizeWithin(details);
    });
    return details;
  }

  function renderRole(role, index, group) {
    const highlights = Array.isArray(role.highlights) ? role.highlights : (role.highlights = []);
    const pagebreak = h("input", { type: "checkbox", checked: Boolean(role.pagebreakBefore) });
    pagebreak.addEventListener("change", () => {
      if (pagebreak.checked) role.pagebreakBefore = true;
      else delete role.pagebreakBefore;
      commit();
    });
    return h("div", { class: "item role" },
      h("div", { class: "role-head" },
        handle(),
        h("strong", {}, "Role"),
        h("label", { class: "check" }, pagebreak, "Start on a new page"),
        itemTools(group.roles, index)),
      h("div", { class: "fields row3" },
        field(role, "position", { label: "Position", required: true }),
        field(role, "startDate", { label: "Start", date: true }),
        field(role, "endDate", { label: "End", date: true, placeholder: "Present" })),
      h("div", { class: "label" }, "Highlights", h("span", { class: "req" }, " *"), h("span", { class: "hint" }, " — the role's bullet points")),
      sortableList(highlights, "highlights", (text, i) => {
        const area = h("textarea", { rows: 1, spellcheck: "true", "data-required": true });
        area.value = text;
        area.addEventListener("input", () => {
          highlights[i] = area.value;
          area.classList.remove("invalid");
          autosize(area);
          commit();
        });
        return h("div", { class: "item duty" }, handle(), area, button("✕", () => change(() => highlights.splice(i, 1)), { class: "danger icon", title: "Delete highlight" }));
      }, "duties"),
      button("+ Add highlight", () => change(() => highlights.push("")), { class: "add" }),
      h("div", { class: "fields" }, field(role, "stack", { label: "Stack", hint: "printed under this role" })));
  }

  // --- render / validate / save ---------------------------------------------------

  function render() {
    if (!model) return;
    const scroll = window.scrollY;
    const shown = [...order, ...SECTIONS.filter((s) => !order.includes(s) && hasData(s))];
    body.replaceChildren(renderBasics(), renderOrderCard(), ...shown.map(renderSection));
    initSortables();
    autosizeWithin(body);
    window.scrollTo(0, scroll);
    undoBtn.disabled = !undoStack.length;
  }

  // Mirrors generate_header.py and generate_resume.py's validate(), so a save
  // here never produces a resume.json that `make build` would reject -- plus
  // blank highlights, which it would happily print as empty bullets. The
  // server also checks the JSON Resume schema itself on save.
  function validate() {
    const problems = [];
    const b = model.basics;
    for (const [k, name] of [["name", "name"], ["label", "title"], ["email", "email"], ["phone", "phone"]]) if (!b[k]) problems.push(`Header: ${name} is required.`);
    if (!(b.location && b.location.city)) problems.push("Header: city is required.");
    if (!b.url && !list(b.profiles).some((p) => p.url)) problems.push("Header: add a website or at least one profile link.");
    for (const key of order) {
      const label = LABELS[key] || key;
      if (key === "summary" && !b.summary) problems.push(`${label} is empty.`);
      if (key === "early_career" && !early.length) problems.push(`${label} has no entries.`);
      if (key === "competencies") list(model.skills).forEach((s, i) => { if (!s.name || !list(s.keywords).length) problems.push(`${label} #${i + 1} needs a name and keywords.`); });
    }
    groups.forEach((group, i) => {
      const where = group.name || `employer #${i + 1}`;
      if (!group.name) problems.push(`Experience ${where}: employer name is required.`);
      group.roles.forEach((role, j) => {
        const roleName = role.position || `role #${j + 1}`;
        if (!role.position) problems.push(`Experience ${where} › ${roleName}: position is required.`);
        if (!list(role.highlights).length) problems.push(`Experience ${where} › ${roleName}: add at least one highlight.`);
        if (list(role.highlights).some((d) => !String(d).trim())) problems.push(`Experience ${where} › ${roleName}: fill in or delete the blank highlight.`);
      });
    });
    // Highlight empty required fields and malformed dates, opening anything
    // collapsed around them.
    let badDates = 0;
    root.querySelectorAll("[data-required], [data-date]").forEach((el) => {
      const value = el.value.trim();
      const bad = (el.dataset.required !== undefined && !value) || (el.dataset.date !== undefined && value && !ISO8601.test(value));
      if (el.dataset.date !== undefined && value && !ISO8601.test(value)) badDates++;
      el.classList.toggle("invalid", bad);
      if (bad) for (let d = el.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
    });
    if (badDates) problems.push(`${badDates} date${badDates === 1 ? " is" : "s are"} not YYYY, YYYY-MM, or YYYY-MM-DD.`);
    if (!problems.length && root.querySelector(".invalid")) problems.push("Fill in the highlighted required fields.");
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

  // The · and – buttons insert at the cursor of the last focused field, since
  // neither character is on most keyboards.
  function insertChar(ch) {
    const el = lastField;
    if (!el || !root.contains(el)) {
      report("Click into a field first, then insert.");
      return;
    }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    el.setRangeText(ch, start, end, "end");
    el.focus();
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  root.addEventListener("focusin", (e) => {
    if (e.target.matches("input[type=text], textarea")) lastField = e.target;
  });
  for (const btn of root.querySelectorAll("[data-insert]")) {
    btn.addEventListener("mousedown", (e) => e.preventDefault()); // keep the field's focus/selection
    btn.addEventListener("click", () => insertChar(btn.dataset.insert));
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
