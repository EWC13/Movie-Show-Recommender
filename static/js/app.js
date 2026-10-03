const form = document.getElementById("recommend-form");
const statusMessage = document.getElementById("status-message");
const resultsEl = document.getElementById("results");

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const submitButton = form.querySelector("button[type=submit]");
  submitButton.disabled = true;
  statusMessage.textContent = "Finding something to watch...";
  resultsEl.innerHTML = "";

  const formData = new FormData(form);
  const moodText = formData.get("mood_text") || "";
  const mediaTypeOverride = formData.get("media_type_override") || null;
  const mode = formData.get("mode") || "keyword";
  const selectedProviderIds = formData
    .getAll("selected_provider_ids")
    .map((v) => parseInt(v, 10));

  const payload = {
    mood_text: moodText,
    media_type_override: mediaTypeOverride,
    selected_provider_ids: selectedProviderIds,
    mode: mode,
  };

  try {
    const response = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      statusMessage.textContent =
        errorBody.detail || "Something went wrong, please try again.";
      return;
    }

    const data = await response.json();
    renderResults(data.results);
  } catch (err) {
    statusMessage.textContent = "Couldn't reach the server, please try again.";
  } finally {
    submitButton.disabled = false;
  }
});

function renderResults(results) {
  if (!results || results.length === 0) {
    statusMessage.textContent =
      "No matches found. Try a broader mood, or select more streaming services.";
    resultsEl.innerHTML = "";
    return;
  }

  statusMessage.textContent = `${results.length} result${results.length === 1 ? "" : "s"}`;

  resultsEl.innerHTML = results.map(renderCard).join("");
}

function renderCard(result) {
  const poster = result.poster_url
    ? `<img class="poster" src="${result.poster_url}" alt="${escapeHtml(result.title)} poster" />`
    : `<div class="poster"></div>`;

  const providerBadges = result.providers
    .map(
      (p) => `
        <span class="provider-badge">
          ${p.logo_url ? `<img src="${p.logo_url}" alt="" />` : ""}
          <span>${escapeHtml(p.name)}</span>
        </span>`
    )
    .join("");

  const providersBlock = result.providers.length
    ? `<div class="providers">${providerBadges}</div>`
    : `<div class="providers providers-empty">Not on your selected services</div>`;

  return `
    <article class="result-card">
      ${poster}
      <div class="body">
        <h3>${escapeHtml(result.title)}</h3>
        ${providersBlock}
        <p class="overview">${escapeHtml(truncate(result.overview, 140))}</p>
      </div>
    </article>
  `;
}

function truncate(text, maxLength) {
  if (!text) return "";
  return text.length > maxLength ? `${text.slice(0, maxLength).trim()}…` : text;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}
