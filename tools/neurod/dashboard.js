const fields = Object.fromEntries(["intent","quality","posterior","margin","dwell","dropped","status"].map(id => [id, document.getElementById(id)]));
async function decode(frequency) {
  fields.status.textContent = "Decoding three deterministic windows…";
  const fault = document.getElementById("fault").value;
  const seed = document.getElementById("seed").value;
  try {
    const response = await fetch(`/api/decode?frequency=${encodeURIComponent(frequency)}&fault=${encodeURIComponent(fault)}&seed=${encodeURIComponent(seed)}`, {cache:"no-store"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "fixture failed");
    fields.intent.textContent = result.label || "ABSTAIN";
    fields.quality.textContent = result.health.quality;
    fields.posterior.textContent = `${result.posterior_permille / 10}%`;
    fields.margin.textContent = `${result.margin_permille / 10}%`;
    fields.dwell.textContent = result.dwell_windows;
    fields.dropped.textContent = result.health.dropped_samples;
    fields.status.textContent = JSON.stringify({synthetic_only:result.synthetic_only,fault:result.fault,os_action_sent:result.os_action_sent}, null, 2);
  } catch (error) {
    fields.status.textContent = `ABSTAIN · ${error.message}`;
  }
}
document.querySelectorAll("button[data-frequency]").forEach(button => button.addEventListener("click", () => decode(button.dataset.frequency)));
