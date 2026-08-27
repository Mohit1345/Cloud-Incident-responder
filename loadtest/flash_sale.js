/**
 * flash_sale.js — Stage C: Stampede traffic (2,000 VUs, 90% hot-key)
 *
 * BEFORE RUNNING:
 *   curl http://localhost:8000/admin/expire-hot-product
 *   k6 run loadtest/flash_sale.js
 */
import http from "k6/http";
import { check } from "k6";
import { Rate, Counter, Trend } from "k6/metrics";

const checkoutErrors   = new Rate("checkout_errors");
const checkoutDuration = new Trend("checkout_duration_ms", true);
const productDuration  = new Trend("product_duration_ms", true);
const hotKeyRequests   = new Counter("hot_key_requests");
const coldKeyRequests  = new Counter("cold_key_requests");

export const options = {
  stages: [
    { duration: "5s",  target: 100 },   // carry-over
    { duration: "10s", target: 300 },   // flash sale starts
    { duration: "15s", target: 500 },   // peak — enough to saturate DB pool
    { duration: "20s", target: 500 },   // sustained
    { duration: "10s", target: 0   },   // ramp down
  ],
  thresholds: {
    http_req_duration: ["p(99)<500"],   // will breach — that's the point
    checkout_errors:   ["rate<0.01"],   // will breach — that's the point
  },
};

const BASE_URL    = __ENV.BASE_URL || "http://localhost:8000";
const CONTROL_IDS = Array.from({ length: 20 }, (_, i) => i + 1);
const HOT_ID      = 123;

function pickProductId() {
  return Math.random() < 0.90
    ? HOT_ID
    : CONTROL_IDS[Math.floor(Math.random() * CONTROL_IDS.length)];
}

export default function () {
  const productId = pickProductId();
  const isHot     = productId === HOT_ID;

  const t0 = Date.now();
  const productRes = http.get(`${BASE_URL}/products/${productId}`, {
    timeout: "12s",
    tags: { name: isHot ? "hot_product" : "cold_product" },
  });
  productDuration.add(Date.now() - t0);
  isHot ? hotKeyRequests.add(1) : coldKeyRequests.add(1);
  check(productRes, { "product 200": (r) => r.status === 200 });

  if (Math.random() < 0.50) {
    const t1 = Date.now();
    const checkoutRes = http.post(
      `${BASE_URL}/checkout`,
      JSON.stringify({ product_id: productId, quantity: 1 }),
      { headers: { "Content-Type": "application/json" }, timeout: "15s", tags: { name: "checkout" } }
    );
    checkoutDuration.add(Date.now() - t1);
    checkoutErrors.add(!check(checkoutRes, { "checkout 200": (r) => r.status === 200 }));
  }
}

export function setup() {
  console.log("=== Flash Sale Stampede Test Starting ===");
  const r  = http.get(`${BASE_URL}/products/${HOT_ID}`);
  const ms = r.timings.duration.toFixed(0);
  console.log(`Initial product fetch: status=${r.status}  duration=${ms}ms`);
  if (r.timings.duration < 150) {
    console.warn("WARNING: Cache may still be warm! Run /admin/expire-hot-product first.");
  } else {
    console.log(`Cache is cold (${ms}ms). GO!`);
  }
}

export function teardown() {
  const r = http.get(`${BASE_URL}/metrics`);
  if (r.status === 200) {
    const m = JSON.parse(r.body);
    console.log("\n=== Incident Snapshot ===");
    console.log(`Cache hit rate:      ${m.cache_hit_rate_pct}%`);
    console.log(`DB pool utilisation: ${m.db_pool_utilization_pct}%`);
    console.log(`Checkout errors:     ${m.checkout_error_pct}%`);
    console.log(`Total requests:      ${m.requests_total}`);
    console.log("=========================");
  }
}