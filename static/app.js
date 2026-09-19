const toast = document.getElementById("toast");

function notify(message, error = false) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 5500);
}

async function postJSON(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

const periodSelect = document.getElementById("periodSelect");
if (periodSelect) {
  periodSelect.addEventListener("change", () => periodSelect.form?.requestSubmit());
}

const updateButton = document.getElementById("updateButton");
if (updateButton) {
  updateButton.addEventListener("click", async () => {
    const oldText = updateButton.textContent;
    const enrich = Boolean(document.getElementById("enrichToggle")?.checked);
    const publisherHtml = enrich && Boolean(document.getElementById("publisherHtmlToggle")?.checked);

    updateButton.disabled = true;
    updateButton.textContent = "Atualizando…";
    notify("Consultando PubMed, Crossref e Europe PMC e consolidando os resultados…");

    try {
      const days = Number(updateButton.dataset.days || 45);
      const data = await postJSON("/api/update", {days, enrich, publisher_html: publisherHtml});
      const src = data.sources || {};
      const sourceText = `PubMed ${src.PubMed || 0}, Crossref ${src.Crossref || 0}, Europe PMC ${src["Europe PMC"] || 0}`;
      const warning = (data.source_errors || []).length ? `; ${(data.source_errors || []).length} fonte(s) com falha parcial` : "";
      const screening = `EM elegíveis ${data.ms_eligible || 0} (alta ${data.ms_high || 0}, moderada ${data.ms_moderate || 0}), pendentes ${data.ms_pending || 0}, excluídos ${data.excluded_not_ms || 0}`;
      notify(`Atualização concluída: ${data.inserted} novos, ${data.updated} atualizados, ${data.deduplicated || 0} duplicatas consolidadas. ${screening}. ${sourceText}${warning}.`);
      window.setTimeout(() => window.location.reload(), 1300);
    } catch (error) {
      notify(`Falha na atualização: ${error.message}`, true);
      updateButton.disabled = false;
      updateButton.textContent = oldText;
    }
  });
}

const doiImportForm = document.getElementById("doiImportForm");
if (doiImportForm) {
  doiImportForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("doiInput");
    const button = document.getElementById("doiImportButton");
    const doi = String(input?.value || "").trim();
    if (!doi) {
      notify("Informe um DOI para importar.", true);
      return;
    }

    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = "Importando…";
    notify("Procurando o DOI no Crossref e no Europe PMC…");

    try {
      const data = await postJSON("/api/import-doi", {
        doi,
        publisher_html: Boolean(document.getElementById("doiPublisherHtml")?.checked),
      });
      const articleId = data.article?.article_id;
      const msStatus = data.article?.ms_eligibility ? ` Especificidade EM: ${data.article.ms_eligibility}.` : "";
      notify((data.inserted ? "Artigo importado e classificado." : "Artigo localizado e atualizado no Radar.") + msStatus);
      if (articleId) {
        window.setTimeout(() => { window.location.href = `/article/${encodeURIComponent(articleId)}`; }, 850);
      } else {
        window.setTimeout(() => window.location.reload(), 850);
      }
    } catch (error) {
      notify(`Não foi possível importar o DOI: ${error.message}`, true);
      button.disabled = false;
      button.textContent = oldText;
    }
  });
}

const enrichArticleButton = document.getElementById("enrichArticleButton");
if (enrichArticleButton) {
  enrichArticleButton.addEventListener("click", async () => {
    const oldText = enrichArticleButton.textContent;
    const articleId = enrichArticleButton.dataset.articleId;
    const htmlToggle = document.getElementById("detailPublisherHtml");
    if (!articleId) return;

    enrichArticleButton.disabled = true;
    enrichArticleButton.textContent = "Enriquecendo…";
    notify("Consultando fontes complementares para este artigo…");

    try {
      const data = await postJSON(`/api/articles/${encodeURIComponent(articleId)}/enrich`, {
        publisher_html: Boolean(htmlToggle?.checked),
      });
      const sourceText = (data.sources || []).length
        ? ` Fontes: ${(data.sources || []).join(", ")}.`
        : " Nenhum metadado novo foi encontrado.";
      const errorText = (data.errors || []).length ? ` Houve ${(data.errors || []).length} falha(s) parcial(is).` : "";
      notify(`Enriquecimento concluído.${sourceText}${errorText}`);
      window.setTimeout(() => window.location.reload(), 1100);
    } catch (error) {
      notify(`Falha no enriquecimento: ${error.message}`, true);
      enrichArticleButton.disabled = false;
      enrichArticleButton.textContent = oldText;
    }
  });
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;

  const card = button.closest(".article-card");
  const articleId = card?.dataset.articleId;
  const action = button.dataset.action;
  if (!articleId || !["favorite", "read"].includes(action)) return;

  button.disabled = true;
  try {
    const data = await postJSON(`/api/articles/${encodeURIComponent(articleId)}/${action}`);
    button.classList.toggle("active", data.value);
    if (action === "read") card.classList.toggle("is-read", data.value);
  } catch (error) {
    notify(`Não foi possível salvar: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
});
