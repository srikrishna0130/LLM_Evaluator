const form = document.querySelector("#evaluation-form");
const promptInput = document.querySelector("#prompt");
const submitButton = document.querySelector("#submit-button");
const formStatus = document.querySelector("#form-status");
const result = document.querySelector("#result");
const evaluationStatus = document.querySelector("#evaluation-status");
const responseGrid = document.querySelector("#response-grid");
const primaryModel = document.querySelector("#primary-model");
const primaryResponse = document.querySelector("#primary-response");
const candidateResult = document.querySelector("#candidate-result");
const candidateModel = document.querySelector("#candidate-model");
const candidateResponse = document.querySelector("#candidate-response");
const scoreResult = document.querySelector("#score-result");
const score = document.querySelector("#score");
const scoreReason = document.querySelector("#score-reason");
const refreshButton = document.querySelector("#refresh-button");
const evaluationsBody = document.querySelector("#evaluations-body");
const evaluationsEmpty = document.querySelector("#evaluations-empty");
const lastUpdated = document.querySelector("#last-updated");

let pollTimeout;
let pollGeneration = 0;

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) {
    const message =
      typeof body.detail === "string" ? body.detail : "Request failed.";
    throw new Error(message);
  }
  return body;
}

function setFormStatus(message, isError = false) {
  formStatus.textContent = message;
  formStatus.classList.toggle("form-error", isError);
}

function setStatus(status) {
  const running = new Set([
    "queued",
    "shadow_running",
    "score_queued",
    "scoring",
  ]);
  evaluationStatus.textContent = status.replaceAll("_", " ");
  evaluationStatus.className = "status";
  if (status === "complete") {
    evaluationStatus.classList.add("status-complete");
  } else if (status === "failed") {
    evaluationStatus.classList.add("status-failed");
  } else if (running.has(status)) {
    evaluationStatus.classList.add("status-running");
  }
}

function resetResult() {
  clearTimeout(pollTimeout);
  pollGeneration += 1;
  candidateResult.hidden = true;
  responseGrid.classList.add("single");
  scoreResult.hidden = true;
  candidateModel.textContent = "";
  candidateResponse.textContent = "";
  score.textContent = "";
  scoreReason.textContent = "";
}

function showEvaluation(evaluation) {
  setStatus(evaluation.status);

  if (evaluation.candidate) {
    candidateResult.hidden = false;
    responseGrid.classList.remove("single");
    candidateModel.textContent = evaluation.candidate.model;
    candidateResponse.textContent = evaluation.candidate.text;
  }

  if (evaluation.comparison) {
    scoreResult.hidden = false;
    score.textContent = `${evaluation.comparison.score.toFixed(2)} / 100`;
    scoreReason.textContent = evaluation.comparison.reason || "";
  }

  if (evaluation.status === "failed") {
    setFormStatus(
      evaluation.error || `Evaluation failed during ${evaluation.error_stage}.`,
      true,
    );
  } else if (evaluation.status === "complete") {
    setFormStatus("Evaluation complete.");
  }
}

async function pollEvaluation(evaluationId, generation, attempt = 0) {
  try {
    const evaluation = await request(
      `/api/v1/evaluations/${encodeURIComponent(evaluationId)}`,
    );
    if (generation !== pollGeneration) {
      return;
    }
    showEvaluation(evaluation);
    if (evaluation.status === "complete" || evaluation.status === "failed") {
      await refreshDashboard();
      return;
    }
  } catch (error) {
    if (generation !== pollGeneration) {
      return;
    }
    setFormStatus(error.message, true);
    return;
  }

  if (attempt < 120) {
    pollTimeout = window.setTimeout(
      () => pollEvaluation(evaluationId, generation, attempt + 1),
      1000,
    );
  } else {
    setFormStatus("The evaluation is still running. Refresh to check again.");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = promptInput.value;
  if (!prompt.trim()) {
    setFormStatus("Enter a prompt first.", true);
    promptInput.focus();
    return;
  }

  resetResult();
  submitButton.disabled = true;
  setFormStatus("Running the primary model…");

  try {
    const response = await request("/api/v1/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    result.hidden = false;
    primaryModel.textContent = response.model;
    primaryResponse.textContent = response.response;

    if (response.sampled) {
      if (response.evaluation_id) {
        setStatus("queued");
        setFormStatus("Primary response returned. Waiting for comparison…");
        pollEvaluation(response.evaluation_id, pollGeneration);
      } else {
        evaluationStatus.textContent = "not stored";
        evaluationStatus.className = "status status-failed";
        setFormStatus(
          "Primary response returned, but the evaluation could not be stored.",
          true,
        );
      }
    } else {
      evaluationStatus.textContent = "not sampled";
      evaluationStatus.className = "status";
      setFormStatus("Primary response returned; this request was not sampled.");
    }
  } catch (error) {
    setFormStatus(error.message, true);
  } finally {
    submitButton.disabled = false;
  }
});

function tableCell(text, className) {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (className) {
    cell.className = className;
  }
  return cell;
}

function shortText(text, limit = 110) {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function renderEvaluations(evaluations) {
  evaluationsBody.replaceChildren();
  evaluationsEmpty.hidden = evaluations.length !== 0;

  for (const evaluation of evaluations) {
    const row = document.createElement("tr");
    const models = evaluation.candidate
      ? `${evaluation.primary.model} / ${evaluation.candidate.model}`
      : evaluation.primary.model;
    const scoreValue = evaluation.comparison
      ? evaluation.comparison.score.toFixed(2)
      : "—";

    row.append(
      tableCell(shortText(evaluation.prompt)),
      tableCell(evaluation.status.replaceAll("_", " "), "table-status"),
      tableCell(models),
      tableCell(scoreValue),
      tableCell(formatDate(evaluation.created_at)),
    );
    evaluationsBody.append(row);
  }
}

async function refreshDashboard() {
  refreshButton.disabled = true;
  try {
    const [metrics, evaluations] = await Promise.all([
      request("/api/v1/metrics"),
      request("/api/v1/evaluations?limit=20"),
    ]);

    document.querySelector("#metric-total").textContent = metrics.total;
    document.querySelector("#metric-completed").textContent = metrics.completed;
    document.querySelector("#metric-failed").textContent = metrics.failed;
    document.querySelector("#metric-average").textContent =
      metrics.average_score === null
        ? "—"
        : metrics.average_score.toFixed(2);
    renderEvaluations(evaluations);
    lastUpdated.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    lastUpdated.textContent = `Unable to refresh: ${error.message}`;
  } finally {
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", refreshDashboard);
refreshDashboard();
