const $ = (id) => document.getElementById(id);

const state = {
  polling: null,
  busy: false,
  series: {
    hitRate: [],
    dbUtil: [],
    errors: [],
  },
};

function log(message) {
  const logEl = $("event-log");
  const time = new Date().toLocaleTimeString();
  const row = document.createElement("div");
  row.className = "event";
  row.textContent = `[${time}] ${message}`;
  logEl.prepend(row);
}

function formatNumber(value) {
  return Number(value ?? 0).toLocaleString();
}

function formatPercent(value) {
  return `${Number(value ?? 0).toFixed(2)}%`;
}

function formatSeconds(value) {
  return `${Number(value ?? 0).toFixed(1)}s`;
}

function setMode(mode) {
  $("status-mode").textContent = mode;

  const pill = $("phase-pill");
  pill.textContent = mode;
  pill.className = "phase-pill";
  if (mode === "Healthy") pill.classList.add("healthy");
  else if (mode === "Stampede") pill.classList.add("danger");
  else pill.classList.add("warn");
}

function setPhase(title, copy) {
  $("phase-title").textContent = title;
  $("phase-copy").textContent = copy;
}

function setBusy(busy) {
  state.busy = busy;
  ["btn-reset", "btn-warm", "btn-expire", "btn-stampede", "btn-guided"].forEach((id) => {
    $(id).disabled = busy;
  });
}

function recordSeriesSample(name, value, limit = 24) {
  const series = state.series[name];
  series.push(Number(value ?? 0));
  if (series.length > limit) series.shift();
}

function renderSparkline(id, values, minValue, maxValue) {
  const points = $(id);
  const width = 100;
  const height = 32;
  if (!values.length) {
    points.setAttribute("points", "");
    return;
  }

  const min = minValue ?? Math.min(...values);
  const max = maxValue ?? Math.max(...values);
  const range = Math.max(max - min, 1);
  const step = width / Math.max(values.length - 1, 1);
  const coords = values.map((value, index) => {
    const x = index * step;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  points.setAttribute("points", coords.join(" "));
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const detail = payload?.detail?.message || payload?.message || response.statusText;
    throw new Error(detail);
  }

  return payload;
}

async function fetchProduct() {
  const data = await api("/products/123");
  $("product-name").textContent = data.name;
  $("product-desc").textContent = data.description || "No description provided.";
  $("product-price").textContent = `$${Number(data.price).toLocaleString()}`;
  $("product-sale").textContent = data.sale_price ? `$${Number(data.sale_price).toLocaleString()}` : "--";
  $("product-stock").textContent = formatNumber(data.stock);
  $("product-card")?.classList.add("flash");
  setTimeout(() => $("product-card")?.classList.remove("flash"), 800);
}

async function refreshMetrics() {
  const data = await api("/metrics");

  $("m-requests").textContent = formatNumber(data.requests_total);
  $("m-errors").textContent = formatNumber(data.errors_total);
  $("m-hits").textContent = formatNumber(data.cache_hits);
  $("m-misses").textContent = formatNumber(data.cache_misses);
  $("m-hit-rate").textContent = formatPercent(data.cache_hit_rate_pct);
  $("m-db-util").textContent = `${Number(data.db_pool_utilization_pct ?? 0).toFixed(1)}%`;
  $("m-checkout-fail").textContent = `${formatNumber(data.checkout_failure)} (${formatPercent(data.checkout_error_pct)})`;
  $("m-uptime").textContent = formatSeconds(data.uptime_seconds);

  $("status-hit-rate").textContent = formatPercent(data.cache_hit_rate_pct);
  $("status-db-util").textContent = `${Number(data.db_pool_utilization_pct ?? 0).toFixed(1)}%`;

  recordSeriesSample("hitRate", data.cache_hit_rate_pct, 24);
  recordSeriesSample("dbUtil", data.db_pool_utilization_pct, 24);
  recordSeriesSample("errors", data.checkout_failure, 24);
  renderSparkline("spark-hit-rate", state.series.hitRate, 0, 100);
  renderSparkline("spark-db-util", state.series.dbUtil, 0, 100);
  renderSparkline("spark-errors", state.series.errors, 0, Math.max(...state.series.errors, 1));
  $("spark-hit-rate-label").textContent = formatPercent(data.cache_hit_rate_pct);
  $("spark-db-util-label").textContent = `${Number(data.db_pool_utilization_pct ?? 0).toFixed(1)}%`;
  $("spark-errors-label").textContent = formatNumber(data.checkout_failure);

  const mode = data.checkout_error_pct > 0 || data.db_pool_utilization_pct > 70
    ? "Stampede"
    : data.cache_hit_rate_pct >= 95
      ? "Healthy"
      : "Degrading";
  setMode(mode);
}

async function resetStats() {
  await api("/admin/reset-stats");
  log("Reset app and Redis counters");
  state.series.hitRate = [];
  state.series.dbUtil = [];
  state.series.errors = [];
  await refreshMetrics();
}

async function warmCache() {
  await api("/admin/warm-cache");
  log("Warmed product:123 in Redis");
  await fetchProduct();
  await refreshMetrics();
}

async function expireHotProduct() {
  const result = await api("/admin/expire-hot-product");
  log(`Expired ${result.key}; stampede window open`);
  setPhase("Stampede window open", "The hot cache entry is gone, so the next requests fall through to PostgreSQL.");
  setMode("Stampede window open");
  await refreshMetrics();
}

async function runStampedeBurst({ expireFirst = true, manageBusy = true } = {}) {
  if (manageBusy && state.busy) return;
  if (manageBusy) setBusy(true);

  const duration = Number($("duration").value);
  const concurrency = Number($("concurrency").value);
  const stopAt = Date.now() + duration * 1000;
  log(`Starting local demo load for ${duration}s at concurrency ${concurrency}`);

  try {
    if (expireFirst) {
      await api("/admin/expire-hot-product");
      log("Hot key expired; firing concurrent product and checkout traffic");
    }
    setPhase(
      "Stampede running",
      "Requests are piling onto the same product key. Watch cache misses and DB utilization climb."
    );
    setMode("Stampede");

    const worker = async () => {
      while (Date.now() < stopAt) {
        const id = Math.random() < 0.9 ? 123 : Math.floor(Math.random() * 20) + 1;
        try {
          await api(`/products/${id}`);
        } catch (err) {
          log(`Product request failed: ${err.message}`);
        }

        if (Math.random() < 0.5) {
          try {
            await api("/checkout", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ product_id: id, quantity: 1 }),
            });
          } catch (err) {
            log(`Checkout failed: ${err.message}`);
          }
        }
      }
    };

    await Promise.all(Array.from({ length: concurrency }, worker));
    log("Stampede demo completed");
    setPhase("Demo complete", "Review the Datadog signals and the app metrics together to explain the incident.");
  } finally {
    if (manageBusy) setBusy(false);
    await refreshMetrics();
  }
}

async function stampedeDemo() {
  await runStampedeBurst({ expireFirst: true, manageBusy: true });
}

async function guidedDemo() {
  if (state.busy) return;
  setBusy(true);
  try {
    log("Guided demo started");
    setPhase("Step 1: Baseline", "Warming the cache so judges can see the healthy state first.");
    setMode("Healthy");
    await resetStats();
    await warmCache();
    await refreshMetrics();
    await new Promise((resolve) => setTimeout(resolve, 1200));

    setPhase("Step 2: Trigger", "Expiring the hot key to open the stampede window.");
    await expireHotProduct();
    await new Promise((resolve) => setTimeout(resolve, 1200));

    setPhase("Step 3: Stampede", "Running the burst so Redis misses and PostgreSQL pressure become visible.");
    await runStampedeBurst({ expireFirst: false, manageBusy: false });

    setPhase("Step 4: Diagnosis", "Now review Datadog first, then corroborate with incident-responder.");
    log("Guided demo finished");
  } catch (err) {
    log(`Guided demo failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

function wireControls() {
  $("duration").addEventListener("input", (event) => {
    $("duration-value").textContent = event.target.value;
  });

  $("concurrency").addEventListener("input", (event) => {
    $("concurrency-value").textContent = event.target.value;
  });

  $("btn-reset").addEventListener("click", () => resetStats().catch((err) => log(err.message)));
  $("btn-warm").addEventListener("click", () => warmCache().catch((err) => log(err.message)));
  $("btn-expire").addEventListener("click", () => expireHotProduct().catch((err) => log(err.message)));
  $("btn-stampede").addEventListener("click", () => stampedeDemo().catch((err) => log(err.message)));
  $("btn-guided").addEventListener("click", () => guidedDemo().catch((err) => log(err.message)));
}

async function bootstrap() {
  wireControls();

  $("duration-value").textContent = $("duration").value;
  $("concurrency-value").textContent = $("concurrency").value;

  try {
    await fetchProduct();
    await refreshMetrics();
    log("Dashboard ready");
    setPhase("Baseline ready", "Warm the cache first, then expire the hot key and start the traffic burst.");
  } catch (err) {
    log(`Startup error: ${err.message}`);
  }

  state.polling = setInterval(() => {
    refreshMetrics().catch((err) => log(`Metrics poll failed: ${err.message}`));
  }, 2000);
}

bootstrap();
