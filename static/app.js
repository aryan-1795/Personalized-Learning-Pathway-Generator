const state = { sessionId: null, question: null, mastery: {}, subject: "python" };
const byId = (id) => document.getElementById(id);

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || "The request failed.");
  return data;
}

function showStatus(message, isError = false) {
  const status = byId("status-message");
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function renderQuestion(question) {
  state.question = question;
  byId("cluster-label").textContent = question.topic_cluster.replaceAll("_", " ");
  byId("difficulty-label").textContent = `Level ${question.difficulty} / 5`;
  byId("question-text").textContent = question.prompt;
  const options = byId("answer-options");
  options.replaceChildren();
  question.options.forEach((option, index) => {
    const label = document.createElement("label");
    label.className = "answer-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "answer";
    input.value = String(index);
    input.required = true;
    const text = document.createElement("span");
    text.textContent = option;
    label.append(input, text);
    options.append(label);
  });
}

byId("start-quiz").addEventListener("click", async () => {
  state.subject = byId("subject").value;
  byId("start-quiz").disabled = true;
  showStatus("Preparing your knowledge check…");
  try {
    const result = await postJson("/api/assessment/start", { subject: state.subject });
    state.sessionId = result.session_id;
    renderQuestion(result.question);
    byId("setup-card").classList.add("hidden");
    byId("quiz-card").classList.remove("hidden");
    showStatus("");
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    byId("start-quiz").disabled = false;
  }
});

byId("answer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = document.querySelector('input[name="answer"]:checked');
  if (!selected || !state.question) return;
  const button = event.currentTarget.querySelector("button[type='submit']");
  button.disabled = true;
  byId("answer-feedback").textContent = "";
  try {
    const result = await postJson("/api/assessment/answer", {
      session_id: state.sessionId,
      question_id: state.question.id,
      selected_index: Number(selected.value),
    });
    byId("answer-feedback").textContent = result.correct ? "Correct. " : "Good try. ";
    byId("answer-feedback").textContent += result.explanation || "";
    if (result.done) {
      state.mastery = result.report.mastery;
      byId("mastery-summary").textContent = `Assessment complete: ${result.report.overall_level} level · ${result.report.questions_answered} questions answered.`;
      byId("quiz-card").classList.add("hidden");
      byId("goal-card").classList.remove("hidden");
    } else {
      window.setTimeout(() => {
        byId("answer-feedback").textContent = "";
        renderQuestion(result.question);
      }, 650);
    }
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});

function appendText(parent, tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  parent.append(node);
  return node;
}

function renderPathway(result) {
  const { pathway, metadata } = result;
  byId("roadmap-title").textContent = pathway.goal;
  byId("total-hours").textContent = `${pathway.total_hours} learning hours`;
  const phaseList = byId("phase-list");
  phaseList.replaceChildren();
  pathway.phases.forEach((phase) => {
    const card = document.createElement("article");
    card.className = "phase-card";
    appendText(card, "h3", "", phase.title);
    phase.steps.forEach((step) => {
      const item = document.createElement("div");
      item.className = "topic-step";
      const titleRow = document.createElement("div");
      titleRow.className = "topic-title-row";
      appendText(titleRow, "span", "topic-title", step.topic_id.replaceAll("-", " "));
      appendText(titleRow, "span", "topic-hours", `${step.hours} hrs${step.review ? " · review" : ""}`);
      item.append(titleRow);
      appendText(item, "p", "", step.rationale);
      appendText(item, "p", "", `Practice: ${step.practice_task}`);
      if (step.resources.length) {
        const links = document.createElement("ul");
        step.resources.forEach((resource) => {
          const li = document.createElement("li");
          const anchor = document.createElement("a");
          anchor.href = resource.url;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          anchor.textContent = resource.verified ? resource.title : `${resource.title} (unverified)`;
          li.append(anchor);
          links.append(li);
        });
        item.append(links);
      }
      card.append(item);
    });
    const checkpoint = document.createElement("div");
    checkpoint.className = "checkpoint";
    appendText(checkpoint, "strong", "", `${phase.checkpoint.title}: `);
    checkpoint.append(document.createTextNode(phase.checkpoint.criteria));
    card.append(checkpoint);
    phaseList.append(card);
  });
  const metadataBox = byId("generation-metadata");
  metadataBox.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "metadata-grid";
  const sourceLabel = { llm_ok: "LLM generated", llm_repaired: "LLM repaired", fallback: "Algorithmic fallback" }[metadata.source] || metadata.source;
  [["Source", sourceLabel], ["Validation", metadata.final_validation_passed ? "Passed" : "Failed"], ["Prompt", metadata.prompt_version], ["Model", metadata.model], ["Latency", `${metadata.latency_ms} ms`], ["Retries", String(metadata.retries)], ["Cache", metadata.cache_hit ? "Hit" : "Miss"]].forEach(([label, value]) => {
    const cell = document.createElement("div");
    cell.className = "metadata-item";
    appendText(cell, "strong", "", label);
    appendText(cell, "span", "", value);
    grid.append(cell);
  });
  metadataBox.append(grid);
  if (metadata.validation_errors?.length) {
    appendText(metadataBox, "p", "validation-errors", `Validation notes: ${metadata.validation_errors.join(" · ")}`);
  }
  byId("goal-card").classList.add("hidden");
  byId("roadmap-section").classList.remove("hidden");
}

byId("generate-pathway").addEventListener("click", async () => {
  const goal = byId("goal").value.trim();
  const budget = Number(byId("budget").value);
  if (!goal || !budget) {
    showStatus("Add a learning goal and a valid hour budget.", true);
    return;
  }
  const button = byId("generate-pathway");
  button.disabled = true;
  showStatus("Building your roadmap from the curated knowledge graph…");
  try {
    const timeframe = Number(byId("weeks").value);
    const goalText = timeframe ? `${goal} (target timeframe: ${timeframe} weeks)` : goal;
    const result = await postJson("/api/pathway/generate", {
      subject: state.subject,
      goal: goalText,
      mastery: state.mastery,
      budget_hours: budget,
    });
    renderPathway(result);
    showStatus("");
    byId("roadmap-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});

byId("start-over").addEventListener("click", () => window.location.reload());
byId("adjust-pathway").addEventListener("click", () => {
  byId("roadmap-section").classList.add("hidden");
  byId("goal-card").classList.remove("hidden");
  byId("goal-card").scrollIntoView({ behavior: "smooth", block: "start" });
});
