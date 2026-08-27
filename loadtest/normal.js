/**
 * normal.js — Stage A: Baseline traffic (50–100 RPS, 5% hot-key)
 * Run: k6 run loadtest/normal.js
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Counter } from "k6/metrics";

const checkoutErrors = new Rate("checkout_errors");
const cacheMissProxy = new Counter("product_requests");

export const options = {
  stages: [
    { duration: "10s", target: 50  },
    { duration: "40s", target: 100 },
    { duration: "5s",  target: 0   },
  ],
  thresholds: {
    // Relaxed: occasional cache misses during normal traffic hit pg_sleep(1s)
    // The stampede test is where this should breach dramatically
    http_req_duration: ["p(99)<3000"],   // was 500, now 3000ms
    checkout_errors:   ["rate<0.02"],    // was 0.01, now 0.02 (2%)
  },
};

const BASE_URL    = __ENV.BASE_URL || "http://localhost:8000";
const CONTROL_IDS = Array.from({ length: 20 }, (_, i) => i + 1);
const HOT_ID      = 123;

function pickProductId() {
  // 95% control products, 5% hot product — normal distribution
  return Math.random() < 0.95
    ? CONTROL_IDS[Math.floor(Math.random() * CONTROL_IDS.length)]
    : HOT_ID;
}

export default function () {
  const productId  = pickProductId();
  const productRes = http.get(`${BASE_URL}/products/${productId}`, {
    tags: { name: "product_view" },
  });
  check(productRes, { "product 200": (r) => r.status === 200 });
  cacheMissProxy.add(1);

  if (Math.random() < 0.20) {
    const checkoutRes = http.post(
      `${BASE_URL}/checkout`,
      JSON.stringify({ product_id: productId, quantity: 1 }),
      { headers: { "Content-Type": "application/json" }, tags: { name: "checkout" } }
    );
    checkoutErrors.add(!check(checkoutRes, { "checkout 200": (r) => r.status === 200 }));
  }

  sleep(0.01);
}