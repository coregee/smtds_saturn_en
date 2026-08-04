const state = {
  bootstrap: null,
  files: [],
  entries: [],
  scope: "",
  search: "",
  statusFilter: "all",
  queryCounts: null,
  total: 0,
  offset: 0,
  limit: 120,
  selected: null,
  originalTranslation: "",
  originalReviewed: false,
  originalExcluded: false,
  reviewBeforeTranslationEdit: false,
  translationEditActive: false,
  dirty: false,
  loading: false,
  fontSets: new Map(),
  preview: null,
  previewVariant: 0,
  previewSequence: 0,
  previewTimer: null,
  previewController: null,
  capacityInFlight: false,
  capacityQueued: null,
  saving: false,
  toastTimer: null,
};

const elements = {
  corpusStatus: document.querySelector("#corpus-status"),
  fileCount: document.querySelector("#file-count"),
  fileList: document.querySelector("#file-list"),
  reload: document.querySelector("#reload"),
  search: document.querySelector("#search"),
  statusFilter: document.querySelector("#status-filter"),
  scopeLabel: document.querySelector("#scope-label"),
  resultCount: document.querySelector("#result-count"),
  queryBreakdown: document.querySelector("#query-breakdown"),
  queryProgress: document.querySelector("#query-progress"),
  dirtyChip: document.querySelector("#dirty-chip"),
  entryList: document.querySelector("#entry-list"),
  loadMore: document.querySelector("#load-more"),
  emptyState: document.querySelector("#empty-state"),
  editorContent: document.querySelector("#editor-content"),
  recordFile: document.querySelector("#record-file"),
  recordLabel: document.querySelector("#record-label"),
  previous: document.querySelector("#previous"),
  next: document.querySelector("#next"),
  previewTitle: document.querySelector("#preview-title"),
  variantControl: document.querySelector("#variant-control"),
  previewVariant: document.querySelector("#preview-variant"),
  previewProfile: document.querySelector("#preview-profile"),
  previewGeometry: document.querySelector("#preview-geometry"),
  previewCapacity: document.querySelector("#preview-capacity"),
  sourceLanguageTag: document.querySelector("#source-language-tag"),
  sourceContextKind: document.querySelector("#source-context-kind"),
  sourcePreview: document.querySelector("#source-preview"),
  sourcePreviewText: document.querySelector("#source-preview-text"),
  translationPreview: document.querySelector("#translation-preview"),
  previewFont: document.querySelector("#preview-font"),
  previewSummary: document.querySelector("#preview-summary"),
  previewNotices: document.querySelector("#preview-notices"),
  sourceFieldLabel: document.querySelector("#source-field-label"),
  sourceField: document.querySelector("#source-field"),
  translationField: document.querySelector("#translation-field"),
  reviewedField: document.querySelector("#reviewed-field"),
  excludedField: document.querySelector("#excluded-field"),
  characterCount: document.querySelector("#character-count"),
  discard: document.querySelector("#discard"),
  save: document.querySelector("#save"),
  metadataSummary: document.querySelector("#metadata-summary"),
  metadataList: document.querySelector("#metadata-list"),
  toast: document.querySelector("#toast"),
};

function escapePreviewText(text) {
  return text.replaceAll("{n}", "\n").replaceAll("{NL}", "\n");
}

function excerpt(text, length = 98) {
  const flat = escapePreviewText(text).replace(/\s+/g, " ").trim();
  return flat.length > length ? `${flat.slice(0, length - 1)}…` : flat || "—";
}

function showToast(message, error = false) {
  window.clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.classList.add("visible");
  state.toastTimer = window.setTimeout(
    () => elements.toast.classList.remove("visible"),
    3200,
  );
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function indexMetrics(font) {
  const glyphs = new Map();
  for (const glyph of font.glyphs) {
    if (!glyphs.has(glyph.text)) {
      glyphs.set(glyph.text, glyph);
    }
    for (const alias of glyph.aliases || []) {
      if (!glyphs.has(alias)) {
        glyphs.set(alias, glyph);
      }
    }
  }
  const compounds = [...glyphs.entries()]
    .filter(([text]) => text.length > 1)
    .sort(([left], [right]) => right.length - left.length);
  return { glyphs, compounds };
}

async function bootstrap() {
  try {
    const data = await requestJson("/api/bootstrap");
    state.bootstrap = data;
    state.files = data.files;
    state.fontSets = new Map(
      Object.entries(data.fonts).map(([name, font]) => [name, indexMetrics(font)]),
    );
    elements.fileCount.textContent = `${data.files.length} JSON files`;
    updateCorpusStatus();
    renderFiles();
    await loadEntries({ reset: true });
  } catch (error) {
    elements.corpusStatus.textContent = "Corpus unavailable";
    showToast(error.message, true);
  }
}

function groupFiles() {
  const groups = new Map();
  for (const file of state.files) {
    if (!groups.has(file.group)) {
      groups.set(file.group, []);
    }
    groups.get(file.group).push(file);
  }
  return groups;
}

function formatStatusCounts(counts, { compact = false } = {}) {
  const values = counts || {
    untranslated: 0,
    translated: 0,
    reviewed: 0,
    excluded: 0,
  };
  if (compact) {
    return (
      `U ${values.untranslated.toLocaleString()} · ` +
      `T ${values.translated.toLocaleString()} · ` +
      `R ${values.reviewed.toLocaleString()} · ` +
      `E ${values.excluded.toLocaleString()}`
    );
  }
  return (
    `${values.untranslated.toLocaleString()} untranslated · ` +
    `${values.translated.toLocaleString()} translated · ` +
    `${values.reviewed.toLocaleString()} reviewed · ` +
    `${values.excluded.toLocaleString()} excluded`
  );
}

function updateCorpusStatus() {
  const total = state.bootstrap?.total || 0;
  elements.corpusStatus.textContent =
    `${total.toLocaleString()} editable fields · ` +
    formatStatusCounts(state.bootstrap?.status_counts);
}

function updateStatusProgress(counts) {
  const values = counts || {};
  for (const segment of elements.queryProgress.querySelectorAll("[data-status]")) {
    const status = segment.dataset.status;
    const count = values[status] || 0;
    segment.style.flexGrow = String(count);
    segment.hidden = count === 0;
    segment.title = `${count.toLocaleString()} ${status}`;
  }
  elements.queryProgress.setAttribute(
    "aria-label",
    formatStatusCounts(counts),
  );
}

function fileButton(label, count, path, counts) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "file-button";
  button.classList.toggle("active", state.scope === path);
  button.dataset.path = path;

  const name = document.createElement("span");
  name.className = "name";
  name.textContent = label;
  const total = document.createElement("span");
  total.className = "count";
  total.textContent = count.toLocaleString();
  button.title = formatStatusCounts(counts);
  button.append(name, total);
  button.addEventListener("click", () => selectScope(path));
  return button;
}

function renderFiles() {
  elements.fileList.replaceChildren();
  const all = fileButton(
    "All corpus",
    state.bootstrap.total,
    "",
    state.bootstrap.status_counts,
  );
  all.classList.add("all-files");
  elements.fileList.append(all);

  for (const [group, files] of groupFiles()) {
    const section = document.createElement("section");
    section.className = "file-group";
    const heading = document.createElement("div");
    heading.className = "file-group-title";
    heading.textContent = group;
    section.append(heading);
    for (const file of files) {
      section.append(
        fileButton(file.name, file.count, file.path, file.status_counts),
      );
    }
    elements.fileList.append(section);
  }
}

async function selectScope(path) {
  if (state.dirty) {
    showToast("Save or discard the current edit before changing sources.", true);
    return;
  }
  state.scope = path;
  state.selected = null;
  renderFiles();
  clearEditor();
  await loadEntries({ reset: true });
}

async function loadEntries({ reset = false } = {}) {
  if (state.loading) {
    return;
  }
  state.loading = true;
  if (reset) {
    state.offset = 0;
    state.entries = [];
    elements.entryList.replaceChildren();
  }
  try {
    const parameters = new URLSearchParams({
      file: state.scope,
      q: state.search,
      status: state.statusFilter,
      offset: String(state.offset),
      limit: String(state.limit),
    });
    const payload = await requestJson(`/api/entries?${parameters}`);
    state.total = payload.total;
    state.queryCounts = payload.status_counts;
    state.entries.push(...payload.entries);
    state.offset = state.entries.length;
    elements.scopeLabel.textContent = state.scope
      ? state.files.find((file) => file.path === state.scope)?.name || state.scope
      : "All corpus";
    elements.resultCount.textContent = `${payload.total.toLocaleString()} matches`;
    elements.queryBreakdown.textContent = formatStatusCounts(
      payload.status_counts,
      { compact: true },
    );
    updateStatusProgress(payload.status_counts);
    renderEntries();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.loading = false;
  }
}

function renderEntries() {
  elements.entryList.replaceChildren();
  if (!state.entries.length) {
    const empty = document.createElement("div");
    empty.className = "entry-empty";
    empty.textContent = "No translation fields match this view.";
    elements.entryList.append(empty);
  }

  for (const entry of state.entries) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "entry-card";
    card.setAttribute("role", "option");
    card.setAttribute("aria-selected", String(state.selected?.id === entry.id));
    card.classList.toggle("active", state.selected?.id === entry.id);
    card.dataset.id = entry.id;

    const header = document.createElement("header");
    const label = document.createElement("strong");
    label.textContent = entry.label;
    const position = document.createElement("span");
    position.className = "entry-position";
    position.textContent = `#${entry.ordinal}`;
    const status = document.createElement("span");
    status.className = `review-badge ${entry.status}`;
    status.textContent = entry.status.replace("-", " ");
    const meta = document.createElement("span");
    meta.className = "entry-meta";
    meta.append(status, position);
    header.append(label, meta);

    const source = document.createElement("p");
    source.className = "source-excerpt";
    source.lang = entry.source_language;
    source.textContent = excerpt(entry.source);
    const translation = document.createElement("p");
    translation.textContent = excerpt(entry.tr);
    card.append(header, source, translation);
    card.addEventListener("click", () => selectEntry(entry.id));
    elements.entryList.append(card);
  }
  elements.loadMore.hidden = state.entries.length >= state.total;
}

function selectEntry(id) {
  if (state.selected?.id === id) {
    return;
  }
  if (state.dirty && state.selected?.id !== id) {
    showToast("Save or discard the current edit before moving on.", true);
    elements.translationField.focus();
    return;
  }
  const entry = state.entries.find((candidate) => candidate.id === id);
  if (!entry) {
    return;
  }
  state.selected = entry;
  state.originalTranslation = entry.tr;
  state.originalReviewed = entry.reviewed;
  state.originalExcluded = entry.excluded;
  state.reviewBeforeTranslationEdit = entry.reviewed;
  state.translationEditActive = false;
  state.dirty = false;
  state.preview = null;
  state.previewVariant = 0;
  elements.emptyState.hidden = true;
  elements.editorContent.hidden = false;
  elements.recordFile.textContent = entry.file;
  elements.recordLabel.textContent = entry.label;
  const sourceIsEnglish = entry.source_language === "en";
  elements.sourceLanguageTag.textContent = sourceIsEnglish ? "EN" : "JP";
  elements.sourceContextKind.textContent = sourceIsEnglish
    ? "reference text"
    : "original text";
  elements.sourceFieldLabel.textContent = sourceIsEnglish
    ? "English reference"
    : "Japanese source";
  elements.sourcePreview.lang = entry.source_language;
  elements.sourceField.lang = entry.source_language;
  elements.sourceField.value = entry.source;
  elements.translationField.value = entry.tr;
  elements.reviewedField.checked = entry.reviewed;
  elements.excludedField.checked = entry.excluded;
  updateDirtyState();
  renderMetadata(entry);
  schedulePreview({ immediate: true });
  for (const card of elements.entryList.querySelectorAll(".entry-card")) {
    const active = card.dataset.id === entry.id;
    card.classList.toggle("active", active);
    card.setAttribute("aria-selected", String(active));
  }
  const active = elements.entryList.querySelector(".entry-card.active");
  active?.scrollIntoView({ block: "nearest" });
}

function clearEditor() {
  state.selected = null;
  state.originalTranslation = "";
  state.originalReviewed = false;
  state.originalExcluded = false;
  state.reviewBeforeTranslationEdit = false;
  state.translationEditActive = false;
  state.dirty = false;
  state.preview = null;
  state.previewVariant = 0;
  state.previewSequence += 1;
  window.clearTimeout(state.previewTimer);
  state.previewTimer = null;
  state.previewController?.abort();
  state.previewController = null;
  state.capacityQueued = null;
  elements.reviewedField.checked = false;
  elements.reviewedField.disabled = true;
  elements.excludedField.checked = false;
  elements.excludedField.disabled = true;
  elements.previewVariant.replaceChildren();
  elements.variantControl.hidden = true;
  elements.emptyState.hidden = false;
  elements.editorContent.hidden = true;
  updateDirtyState();
}

function renderMetadata(entry) {
  elements.metadataList.replaceChildren();
  const rows = [
    ["file", entry.file],
    ["JSON path", formatPointer(entry.pointer)],
    ...Object.entries(entry.metadata),
  ];
  elements.metadataSummary.textContent = `${rows.length} fields`;
  for (const [key, value] of rows) {
    const term = document.createElement("dt");
    term.textContent = key.replaceAll("_", " ");
    const detail = document.createElement("dd");
    detail.textContent =
      typeof value === "string" ? value : JSON.stringify(value, null, 2);
    elements.metadataList.append(term, detail);
  }
}

function formatPointer(pointer) {
  return pointer
    .map((part) => (typeof part === "number" ? `[${part}]` : `.${part}`))
    .join("")
    .replace(/^\./, "$.");
}

function segmentText(
  text,
  warnings,
  variant,
  tokenWidths = variant.token_widths,
) {
  const fontSet = state.fontSets.get(variant.font);
  const fixedGlyphs = variant.glyph_widths || {};
  const fixedCompounds = Object.keys(fixedGlyphs)
    .filter((value) => value.length > 1)
    .sort((left, right) => right.length - left.length);
  const fallbackWidth =
    variant.fixed_advance || (variant.font === "font12" ? 12 : 16);
  const segments = [];
  let position = 0;
  while (position < text.length) {
    if (text[position] === "{") {
      const end = text.indexOf("}", position);
      if (end !== -1) {
        const token = text.slice(position, end + 1);
        segments.push({
          kind: "token",
          text: token,
          width: tokenWidths[token] ?? 0,
        });
        position = end + 1;
        continue;
      }
    }

    const compound =
      fontSet?.compounds.find(([candidate]) =>
        text.startsWith(candidate, position),
      ) ||
      fixedCompounds
        .filter((candidate) => text.startsWith(candidate, position))
        .map((candidate) => [candidate, { advance: fixedGlyphs[candidate] }])[0];
    if (compound) {
      const [candidate, glyph] = compound;
      segments.push({ kind: "glyph", text: candidate, width: glyph.advance });
      position += candidate.length;
      continue;
    }

    const character = text[position];
    const glyph = fontSet?.glyphs.get(character);
    if (glyph) {
      segments.push({ kind: "glyph", text: character, width: glyph.advance });
    } else if (fixedGlyphs[character] !== undefined) {
      segments.push({
        kind: "glyph",
        text: character,
        width: fixedGlyphs[character],
      });
    } else if (
      variant.fixed_advance &&
      character.codePointAt(0) >= 0x20 &&
      character.codePointAt(0) <= 0x7e
    ) {
      segments.push({
        kind: "glyph",
        text: character,
        width: variant.fixed_advance,
      });
    } else {
      segments.push({ kind: "unknown", text: character, width: fallbackWidth });
      warnings.add(character);
    }
    position += 1;
  }
  return segments;
}

function renderPixelLine(line, variant, warnings) {
  const contentWidth = variant.content_width || variant.surface_width || 320;
  const row = document.createElement("div");
  row.className = "pixel-line";
  row.style.width = `${contentWidth}px`;
  row.style.marginLeft = `${variant.left_margin}px`;
  row.style.columnGap = `${variant.glyph_gap || 0}px`;
  row.classList.toggle(
    "overflow",
    line.width !== null &&
      variant.content_width !== null &&
      line.width > variant.content_width,
  );
  row.title = line.width === null ? "Width unavailable" : `${line.width}px`;
  for (const segment of segmentText(line.text, warnings, variant)) {
    const span = document.createElement("span");
    span.style.width = `${segment.width}px`;
    if (segment.kind === "token") {
      span.className = "inline-token";
      span.title = `${segment.text}: ${segment.width}px reserved`;
      if (segment.width === 0) {
        span.classList.add("zero-width");
        const label = document.createElement("span");
        label.textContent = segment.text.slice(1, -1);
        span.append(label);
      } else {
        span.textContent = segment.text.slice(1, -1);
      }
    } else {
      span.className = "glyph";
      span.textContent = segment.text;
      if (segment.kind === "unknown") {
        span.title = `Unsupported ${variant.font_label}: ${segment.text}`;
      }
    }
    row.append(span);
  }
  return row;
}

function menuSlotPreview(item, variant) {
  return (item?.slot_previews || []).find(
    (preview) => preview.variant_id === variant.id,
  );
}

function menuSlotOverflowSummary(slotPreview) {
  const details = [];
  if (
    Number.isFinite(slotPreview.line_count) &&
    Number.isFinite(slotPreview.max_lines) &&
    slotPreview.line_count > slotPreview.max_lines
  ) {
    details.push(`${slotPreview.line_count}/${slotPreview.max_lines} lines`);
  }

  const measuredWidths = (slotPreview.lines || [])
    .map((line) => line.width)
    .filter((width) => Number.isFinite(width));
  const longest = measuredWidths.length ? Math.max(...measuredWidths) : null;
  if (
    longest !== null &&
    Number.isFinite(slotPreview.content_width) &&
    longest > slotPreview.content_width
  ) {
    details.push(`${longest}/${slotPreview.content_width}px`);
  }
  if (slotPreview.error) {
    details.push("measurement error");
  }
  return details.join(" · ") || "overflow";
}

function markMenuSlot(
  slot,
  slotPreview,
  label,
  geometryExact,
  overflowDetails,
) {
  if (!slotPreview) {
    return;
  }
  if (Number.isFinite(slotPreview.content_width)) {
    slot.style.setProperty(
      "--menu-slot-width",
      `${slotPreview.content_width}px`,
    );
  }
  if (!slotPreview.overflow) {
    return;
  }

  const summary = menuSlotOverflowSummary(slotPreview);
  slot.classList.add("slot-overflow");
  const badge = document.createElement("span");
  badge.className = "menu-overflow-badge";
  badge.textContent = summary;
  slot.append(badge);
  overflowDetails.push({
    label,
    summary,
    exact: Boolean(geometryExact && slotPreview.exact),
    error: slotPreview.error,
  });
}

function renderMenuCopy(text, variant, warnings, slotPreview = null) {
  const copy = document.createElement("div");
  copy.className = "menu-copy";
  const fallbackLines = escapePreviewText(text)
    .split("\n")
    .map((line) => ({ text: line, width: null }));
  const lines = slotPreview?.lines?.length ? slotPreview.lines : fallbackLines;
  for (const line of lines) {
    const row = document.createElement("div");
    row.className = "menu-line";
    const lineOverflows = Boolean(
      Number.isFinite(line.width) &&
        Number.isFinite(slotPreview?.content_width) &&
        line.width > slotPreview.content_width,
    );
    row.classList.toggle("line-overflow", lineOverflows);
    if (Number.isFinite(line.width)) {
      row.title = Number.isFinite(slotPreview?.content_width)
        ? `${line.width}/${slotPreview.content_width}px`
        : `${line.width}px`;
    }
    const tokenWidths = slotPreview?.token_widths || variant.token_widths;
    for (const segment of segmentText(
      line.text,
      warnings,
      variant,
      tokenWidths,
    )) {
      const span = document.createElement("span");
      span.className = segment.kind === "token" ? "inline-token" : "glyph";
      span.style.width = `${segment.width}px`;
      span.textContent =
        segment.kind === "token" ? segment.text.slice(1, -1) : segment.text;
      row.append(span);
    }
    copy.append(row);
  }
  return copy;
}

function renderMenuContexts(variant, warnings) {
  const menus = state.preview?.menus || [];
  const overflowDetails = [];
  menus.forEach((menu, menuIndex) => {
    const context = document.createElement("section");
    context.className = "menu-context";
    context.classList.toggle("exact-geometry", menu.geometry_exact);

    const promptSlotPreview = menuSlotPreview(menu.prompt, variant);
    const optionSlotPreviews = menu.options.map((option) =>
      menuSlotPreview(option, variant),
    );
    const optionSlotWidth = optionSlotPreviews.find((preview) =>
      Number.isFinite(preview?.content_width),
    )?.content_width;
    const stageWidth =
      promptSlotPreview?.content_width ||
      (Number.isFinite(optionSlotWidth) ? optionSlotWidth * 2 : null) ||
      variant.surface_width;
    if (menu.geometry_exact && Number.isFinite(stageWidth)) {
      context.style.setProperty("--menu-stage-width", `${stageWidth}px`);
    }
    if (menu.geometry_exact && Number.isFinite(optionSlotWidth)) {
      context.style.setProperty(
        "--menu-option-width",
        `${optionSlotWidth}px`,
      );
    }

    const contract = document.createElement("div");
    contract.className = "menu-contract";
    contract.textContent =
      `Dialogue choice ${menuIndex + 1} · ${menu.options.length} options · ` +
      `${menu.option_slots}-slot grid`;
    context.append(contract);

    if (menu.prompt?.tr) {
      const prompt = document.createElement("div");
      prompt.className = "menu-prompt";
      prompt.append(
        renderMenuCopy(
          menu.prompt.tr,
          variant,
          warnings,
          promptSlotPreview,
        ),
      );
      markMenuSlot(
        prompt,
        promptSlotPreview,
        `Dialogue choice ${menuIndex + 1} prompt`,
        menu.geometry_exact,
        overflowDetails,
      );
      context.append(prompt);
    }

    const grid = document.createElement("div");
    grid.className = "menu-option-grid";
    for (const [optionIndex, option] of menu.options.entries()) {
      const cell = document.createElement("div");
      cell.className = "menu-option";
      cell.classList.toggle("selected", option.selected);
      const slotPreview = optionSlotPreviews[optionIndex];
      cell.append(
        renderMenuCopy(option.tr, variant, warnings, slotPreview),
      );
      markMenuSlot(
        cell,
        slotPreview,
        `Dialogue choice ${menuIndex + 1} option ${optionIndex + 1}`,
        menu.geometry_exact,
        overflowDetails,
      );
      grid.append(cell);
    }
    for (let index = menu.options.length; index < menu.option_slots; index += 1) {
      const empty = document.createElement("div");
      empty.className = "menu-option empty";
      empty.setAttribute("aria-hidden", "true");
      grid.append(empty);
    }
    context.append(grid);
    elements.translationPreview.append(context);
  });
  return overflowDetails;
}

function renderVariantControls() {
  const variants = state.preview?.variants || [];
  elements.previewVariant.replaceChildren();
  variants.forEach((variant, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = variant.label;
    elements.previewVariant.append(option);
  });
  elements.previewVariant.value = String(state.previewVariant);
  elements.variantControl.hidden = variants.length <= 1;
}

function renderPreview() {
  if (!state.selected) {
    return;
  }
  const translation = elements.translationField.value;
  const variants = state.preview?.variants || [];
  const variant = variants[state.previewVariant];
  elements.characterCount.textContent =
    `${translation.length.toLocaleString()} ${translation.length === 1 ? "char" : "chars"}`;
  if (!variant) {
    elements.previewSummary.textContent = "Measuring…";
    return;
  }

  const surfaceWidth = variant.surface_width || variant.content_width || 320;
  const contentWidth = variant.content_width || surfaceWidth;
  elements.sourcePreview.style.width = `${surfaceWidth}px`;
  elements.translationPreview.style.width = `${surfaceWidth}px`;
  elements.translationPreview.dataset.font = variant.font;
  elements.sourcePreviewText.style.width = `${contentWidth}px`;
  elements.sourcePreviewText.style.marginLeft = `${variant.left_margin}px`;
  elements.sourcePreviewText.textContent = escapePreviewText(state.selected.source);
  elements.translationPreview.replaceChildren();

  const renderWarnings = new Set();
  const pageStarts = new Map();
  let pageStart = 0;
  variant.page_line_counts.slice(0, -1).forEach((lineCount, index) => {
    pageStart += lineCount;
    pageStarts.set(pageStart, index + 2);
  });
  variant.lines.forEach((line, index) => {
    if (pageStarts.has(index)) {
      const divider = document.createElement("div");
      divider.className = "page-divider";
      divider.style.width = `${contentWidth}px`;
      divider.style.marginLeft = `${variant.left_margin}px`;
      const label = document.createElement("span");
      label.textContent = `page ${pageStarts.get(index)}`;
      divider.append(label);
      elements.translationPreview.append(divider);
    }
    elements.translationPreview.append(
      renderPixelLine(line, variant, renderWarnings),
    );
  });
  const menuOverflows = renderMenuContexts(variant, renderWarnings);

  const measuredWidths = variant.lines
    .map((line) => line.width)
    .filter((width) => width !== null);
  const longest = measuredWidths.length ? Math.max(...measuredWidths) : null;
  const pages = variant.page_line_counts.length;
  const widthSummary =
    longest === null || variant.content_width === null
      ? "unbounded"
      : `${longest}/${variant.content_width}px`;
  elements.previewSummary.textContent =
    `${widthSummary} · ${variant.lines.length} ` +
    `${variant.lines.length === 1 ? "line" : "lines"} · ${pages} ` +
    `${pages === 1 ? "page" : "pages"}`;
  elements.previewFont.textContent = variant.font_label;
  elements.previewProfile.textContent =
    `${variant.profile.replaceAll("_", " ")}${variant.exact ? "" : " · advisory"}`;
  elements.previewGeometry.textContent =
    variant.content_width === null
      ? "No pixel-wrap rule"
      : variant.left_margin || variant.right_margin
        ? `${variant.content_width}px usable · ${variant.left_margin}+${variant.right_margin}px margins`
        : `${variant.content_width}px usable · no side margins`;

  const capacity = state.preview?.capacity;
  if (capacity) {
    const advisory = capacity.exact ? "" : " · advisory";
    elements.previewCapacity.textContent =
      `Capacity ${capacity.outcome}${advisory}`;
    elements.previewCapacity.classList.toggle(
      "warning",
      capacity.outcome === "runtime" || !capacity.exact,
    );
    elements.previewCapacity.classList.toggle(
      "danger",
      capacity.outcome === "fallback" || capacity.outcome === "overflow",
    );
  } else {
    elements.previewCapacity.textContent = "Capacity measuring…";
    elements.previewCapacity.classList.remove("warning", "danger");
  }

  elements.previewNotices.replaceChildren();
  for (const constraint of variant.constraints) {
    addNotice(constraint);
  }
  if (variant.error) {
    addNotice(variant.error, "danger");
  }
  const overflowCount = variant.lines.filter(
    (line) =>
      line.width !== null &&
      variant.content_width !== null &&
      line.width > variant.content_width,
  ).length;
  if (overflowCount) {
    addNotice(
      `${overflowCount} over-width ${overflowCount === 1 ? "line" : "lines"}`,
      "danger",
    );
  } else if (longest !== null && variant.content_width !== null) {
    addNotice(`Longest line has ${variant.content_width - longest}px spare`);
  }
  for (const detail of menuOverflows) {
    const advisory = detail.exact ? "" : " · advisory geometry";
    const error = detail.error ? ` · ${detail.error}` : "";
    addNotice(
      `${detail.label} exceeds its slot: ${detail.summary}${advisory}${error}`,
      "danger",
    );
  }
  if (renderWarnings.size) {
    addNotice(
      `Unsupported ${variant.font_label}: ${[...renderWarnings].map((value) => JSON.stringify(value)).join(", ")}`,
      "warning",
    );
  }
  const reservations = [...new Set(Object.values(variant.token_widths))]
    .filter((width) => width > 0)
    .sort((left, right) => left - right);
  if (reservations.length) {
    addNotice(
      `Inline inserts reserve ${reservations.map((width) => `${width}px`).join(", ")}`,
      "warning",
    );
  }
  const menus = state.preview?.menus || [];
  if (menus.length) {
    if (menus.every((menu) => menu.geometry_exact)) {
      addNotice(
        "Dialogue option membership/order and COMBAT 320px prompt / 2×160px option geometry are verified",
      );
    } else {
      addNotice(
        "Dialogue option membership/order is verified from EVE opcodes; window geometry is advisory",
        "warning",
      );
    }
  }
  if (capacity) {
    for (const check of capacity.checks || []) {
      const measurement =
        check.used !== null && check.capacity !== null
          ? `${check.used}/${check.capacity} ${check.unit}`
          : check.used !== null
            ? `${check.used} ${check.unit}`
            : "";
      const detail = [
        check.name.replaceAll("_", " "),
        measurement,
        check.message,
      ]
        .filter(Boolean)
        .join(" · ");
      const kind =
        check.outcome === "overflow" || check.outcome === "fallback"
          ? "danger"
          : check.outcome === "runtime" || !check.exact
            ? "warning"
            : "";
      addNotice(detail, kind);
    }
    if (capacity.runtime_requirements?.length) {
      addNotice(
        `Runtime capacity owner: ${capacity.runtime_requirements.join(", ")}`,
        "warning",
      );
    }
    if (capacity.note) {
      addNotice(capacity.note, capacity.exact ? "" : "warning");
    }
  }
}

async function requestPreview() {
  if (!state.selected || state.saving) {
    return;
  }
  const sequence = ++state.previewSequence;
  const request = {
    file: state.selected.file,
    pointer: state.selected.pointer,
    tr: elements.translationField.value,
  };
  state.previewController?.abort();
  const controller = new AbortController();
  state.previewController = controller;
  elements.previewSummary.textContent = "Measuring…";
  elements.previewCapacity.textContent = "Capacity measuring…";
  elements.previewCapacity.classList.remove("warning", "danger");
  try {
    const preview = await requestJson("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (sequence !== state.previewSequence || !state.selected) {
      return;
    }
    state.preview = preview;
    state.previewVariant = Math.min(
      state.previewVariant,
      Math.max(0, preview.variants.length - 1),
    );
    renderVariantControls();
    renderPreview();
    queueCapacity({ sequence, request });
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    if (sequence !== state.previewSequence) {
      return;
    }
    elements.previewSummary.textContent = "Preview unavailable";
    elements.previewCapacity.textContent = "Capacity unavailable";
    elements.previewCapacity.classList.add("danger");
    elements.previewNotices.replaceChildren();
    addNotice(error.message, "danger");
  } finally {
    if (state.previewController === controller) {
      state.previewController = null;
    }
  }
}

function queueCapacity(job) {
  state.capacityQueued = job;
  drainCapacityQueue();
}

async function drainCapacityQueue() {
  if (state.capacityInFlight || state.saving || !state.capacityQueued) {
    return;
  }
  const job = state.capacityQueued;
  state.capacityQueued = null;
  if (job.sequence !== state.previewSequence || !state.selected) {
    drainCapacityQueue();
    return;
  }
  state.capacityInFlight = true;
  try {
    const capacity = await requestJson("/api/capacity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job.request),
    });
    if (job.sequence === state.previewSequence && state.preview) {
      state.preview.capacity = capacity;
      renderPreview();
    }
  } catch (error) {
    if (job.sequence === state.previewSequence && state.preview) {
      elements.previewCapacity.textContent = "Capacity unavailable";
      elements.previewCapacity.classList.add("danger");
      addNotice(error.message, "danger");
    }
  } finally {
    state.capacityInFlight = false;
    if (state.capacityQueued) {
      drainCapacityQueue();
    }
  }
}

function schedulePreview({ immediate = false } = {}) {
  window.clearTimeout(state.previewTimer);
  state.previewTimer = null;
  if (state.saving) {
    return;
  }
  if (immediate) {
    requestPreview();
    return;
  }
  state.previewSequence += 1;
  state.previewController?.abort();
  state.previewController = null;
  state.capacityQueued = null;
  state.previewTimer = window.setTimeout(requestPreview, 200);
}

function addNotice(text, kind = "") {
  const notice = document.createElement("span");
  notice.className = `notice ${kind}`.trim();
  notice.textContent = text;
  elements.previewNotices.append(notice);
}

function updateDirtyState() {
  const translationChanged = Boolean(
    state.selected &&
      elements.translationField.value !== state.originalTranslation,
  );
  if (translationChanged) {
    if (!state.translationEditActive) {
      state.reviewBeforeTranslationEdit = elements.reviewedField.checked;
      state.translationEditActive = true;
    }
    elements.reviewedField.checked = true;
  } else if (state.translationEditActive) {
    elements.reviewedField.checked = state.reviewBeforeTranslationEdit;
    state.translationEditActive = false;
  }
  elements.reviewedField.disabled = !state.selected || translationChanged;
  elements.excludedField.disabled = !state.selected;
  const reviewChanged = Boolean(
    state.selected &&
      elements.reviewedField.checked !== state.originalReviewed,
  );
  const exclusionChanged = Boolean(
    state.selected &&
      elements.excludedField.checked !== state.originalExcluded,
  );
  state.dirty = translationChanged || reviewChanged || exclusionChanged;
  elements.dirtyChip.hidden = !state.dirty;
  elements.save.disabled = !state.dirty || state.saving;
  elements.discard.disabled = !state.dirty || state.saving;
}

function discardChanges() {
  if (!state.selected) {
    return;
  }
  elements.translationField.value = state.originalTranslation;
  elements.reviewedField.checked = state.originalReviewed;
  elements.excludedField.checked = state.originalExcluded;
  state.reviewBeforeTranslationEdit = state.originalReviewed;
  state.translationEditActive = false;
  updateDirtyState();
  schedulePreview({ immediate: true });
  showToast("Unsaved changes discarded.");
}

async function saveChanges() {
  if (!state.selected || !state.dirty || state.saving) {
    return;
  }
  state.saving = true;
  window.clearTimeout(state.previewTimer);
  state.previewTimer = null;
  state.previewSequence += 1;
  state.previewController?.abort();
  state.previewController = null;
  state.capacityQueued = null;
  updateDirtyState();
  elements.save.textContent = "Saving…";
  const savedId = state.selected.id;
  try {
    const translation = elements.translationField.value;
    const priorStatus = state.selected.status;
    const savedFile = state.selected.file;
    const result = await requestJson("/api/entry", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Editor-Token": state.bootstrap.editor_token,
      },
      body: JSON.stringify({
        file: state.selected.file,
        pointer: state.selected.pointer,
        expected_tr: state.originalTranslation,
        tr: translation,
        expected_reviewed: state.originalReviewed,
        reviewed: elements.reviewedField.checked,
        expected_excluded: state.originalExcluded,
        excluded: elements.excludedField.checked,
      }),
    });
    state.originalTranslation = result.tr;
    state.originalReviewed = result.reviewed;
    state.originalExcluded = result.excluded;
    state.reviewBeforeTranslationEdit = result.reviewed;
    state.translationEditActive = false;
    state.selected.tr = result.tr;
    state.selected.reviewed = result.reviewed;
    state.selected.excluded = result.excluded;
    state.selected.status = result.status;
    elements.translationField.value = result.tr;
    elements.reviewedField.checked = result.reviewed;
    elements.excludedField.checked = result.excluded;
    adjustStatusCounts(savedFile, priorStatus, result.status);
    updateDirtyState();
    if (state.search) {
      await loadEntries({ reset: true });
      if (!state.entries.some((entry) => entry.id === savedId)) {
        clearEditor();
      }
      showToast(`Saved ${savedFile} in place.`);
      return;
    }
    if (!statusFilterMatches(result.status)) {
      state.entries = state.entries.filter((entry) => entry.id !== savedId);
      state.total = Math.max(0, state.total - 1);
      elements.resultCount.textContent = `${state.total.toLocaleString()} matches`;
      clearEditor();
    }
    renderEntries();
    showToast(`Saved ${savedFile} in place.`);
  } catch (error) {
    if (error.status === 409) {
      showToast("This field changed on disk. Reload before saving again.", true);
    } else {
      showToast(error.message, true);
    }
  } finally {
    state.saving = false;
    elements.save.textContent = "Save to corpus";
    updateDirtyState();
    if (state.selected?.id === savedId) {
      schedulePreview({ immediate: true });
    } else {
      drainCapacityQueue();
    }
  }
}

function statusFilterMatches(status) {
  return state.statusFilter === "all" || state.statusFilter === status;
}

function moveStatusCount(counts, before, after) {
  if (!counts || before === after) {
    return;
  }
  counts[before] -= 1;
  counts[after] += 1;
}

function adjustStatusCounts(file, before, after) {
  if (before === after) {
    return;
  }
  moveStatusCount(state.bootstrap.status_counts, before, after);
  const fileEntry = state.files.find((entry) => entry.path === file);
  if (fileEntry) {
    moveStatusCount(fileEntry.status_counts, before, after);
  }
  moveStatusCount(state.queryCounts, before, after);
  updateCorpusStatus();
  elements.queryBreakdown.textContent = formatStatusCounts(state.queryCounts, {
    compact: true,
  });
  updateStatusProgress(state.queryCounts);
  renderFiles();
}

function moveSelection(delta) {
  if (!state.selected || state.dirty) {
    if (state.dirty) {
      showToast("Save or discard the current edit before moving on.", true);
    }
    return;
  }
  const index = state.entries.findIndex((entry) => entry.id === state.selected.id);
  const target = state.entries[index + delta];
  if (target) {
    selectEntry(target.id);
  }
}

function updateNavigation() {
  if (!state.selected) {
    elements.previous.disabled = true;
    elements.next.disabled = true;
    return;
  }
  const index = state.entries.findIndex((entry) => entry.id === state.selected.id);
  elements.previous.disabled = index <= 0;
  elements.next.disabled = index < 0 || index >= state.entries.length - 1;
}

let searchTimer = null;
elements.search.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(async () => {
    if (state.dirty) {
      showToast("Save or discard the current edit before searching.", true);
      elements.search.value = state.search;
      return;
    }
    state.search = elements.search.value;
    state.selected = null;
    clearEditor();
    await loadEntries({ reset: true });
  }, 180);
});

elements.reload.addEventListener("click", async () => {
  if (state.dirty) {
    showToast("Save or discard the current edit before reloading.", true);
    return;
  }
  await bootstrap();
  showToast("Corpus index refreshed.");
});
elements.loadMore.addEventListener("click", () => loadEntries());
elements.translationField.addEventListener("input", () => {
  updateDirtyState();
  schedulePreview();
});
elements.reviewedField.addEventListener("change", updateDirtyState);
elements.excludedField.addEventListener("change", updateDirtyState);
elements.statusFilter.addEventListener("change", async () => {
  if (state.dirty) {
    showToast("Save or discard the current edit before filtering.", true);
    elements.statusFilter.value = state.statusFilter;
    return;
  }
  state.statusFilter = elements.statusFilter.value;
  clearEditor();
  await loadEntries({ reset: true });
});
elements.previewVariant.addEventListener("change", () => {
  state.previewVariant = Number(elements.previewVariant.value);
  renderPreview();
});
elements.save.addEventListener("click", saveChanges);
elements.discard.addEventListener("click", discardChanges);
elements.previous.addEventListener("click", () => moveSelection(-1));
elements.next.addEventListener("click", () => moveSelection(1));

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveChanges();
    return;
  }
  if (
    event.key === "/" &&
    !event.ctrlKey &&
    !event.metaKey &&
    document.activeElement !== elements.translationField
  ) {
    event.preventDefault();
    elements.search.focus();
    return;
  }
  if (event.altKey && event.key === "ArrowUp") {
    event.preventDefault();
    moveSelection(-1);
  }
  if (event.altKey && event.key === "ArrowDown") {
    event.preventDefault();
    moveSelection(1);
  }
});

window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

const observer = new MutationObserver(updateNavigation);
observer.observe(elements.entryList, { childList: true, subtree: true });

bootstrap();
