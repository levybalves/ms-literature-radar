const toast = document.getElementById("toast");

function notify(message, error = false) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 4500);
}

async function postJSON(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

// Trocar o período atualiza o painel imediatamente; os demais filtros continuam
// disponíveis no mesmo formulário e são preservados no envio.
const periodSelect = document.getElementById("periodSelect");
if (periodSelect) {
  periodSelect.addEventListener("change", () => {
    periodSelect.form?.requestSubmit();
  });
}

const updateButton = document.getElementById("updateButton");
if (updateButton) {
  updateButton.addEventListener("click", async () => {
    const oldText = updateButton.textContent;
    updateButton.disabled = true;
    updateButton.textContent = "Atualizando…";
    notify("Consultando o PubMed e classificando os artigos…");

    try {
      const days = Number(updateButton.dataset.days || 45);
      const data = await postJSON("/api/update", {days});
      notify(
        `Atualização concluída: ${data.inserted} novos; ${data.updated} registros atualizados.`
      );
      window.setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      notify(`Falha na atualização: ${error.message}`, true);
      updateButton.disabled = false;
      updateButton.textContent = oldText;
    }
  });
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;

  const card = button.closest(".article-card");
  const pmid = card?.dataset.pmid;
  const action = button.dataset.action;
  if (!pmid || !["favorite", "read"].includes(action)) return;

  button.disabled = true;
  try {
    const data = await postJSON(`/api/articles/${pmid}/${action}`);
    button.classList.toggle("active", data.value);
    if (action === "read") {
      card.classList.toggle("is-read", data.value);
    }
  } catch (error) {
    notify(`Não foi possível salvar: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
});
