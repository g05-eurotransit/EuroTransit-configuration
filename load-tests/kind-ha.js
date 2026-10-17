// Use the existing checkout contract and ledger, with bounded spacing across a worker failure.
import { sleep } from 'k6';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import { checkout as placeOrder, setup, handleSummary } from './checkout.js';
import { integer } from './config.mjs';
export { setup, handleSummary };
const attempts = integer(__ENV.MAX_ATTEMPTS, 8, 1, 8, 'MAX_ATTEMPTS');
const duration = integer(__ENV.HA_OBSERVE_SECONDS, 180, 120, 300, 'HA_OBSERVE_SECONDS');
const interval = integer(__ENV.HA_CHECKOUT_INTERVAL_SECONDS, 12, 5, 30, 'HA_CHECKOUT_INTERVAL_SECONDS');
const samples = new Counter('ha_catalog_samples');
const errors = new Counter('ha_catalog_errors');
const latency = new Trend('ha_catalog_ms', true);
export const options = {
  insecureSkipTLSVerify: __ENV.ALLOW_INSECURE_TLS === 'true',
  scenarios: {
    checkout: { executor: 'shared-iterations', vus: 1, iterations: attempts, maxDuration: '480s', exec: 'checkout' },
    browse: { executor: 'constant-vus', vus: 1, duration: `${duration}s`, gracefulStop: '5s', exec: 'browse' },
  },
  thresholds: { checkout_assertion_failures: ['count==0'], ha_catalog_errors: ['count==0'] },
};
export function checkout() { placeOrder(); sleep(interval); }
export function browse() {
  errors.add(0);
  const r = http.get(`${__ENV.PUBLIC_URL}/api/catalog/routes`, { timeout: '5s', tags: { operation: 'ha_catalog' } });
  samples.add(1); latency.add(r.timings.duration);
  if (r.status !== 200) errors.add(1);
  console.log(`ET_HA_CATALOG ${JSON.stringify({ at: new Date().toISOString(), status: r.status, durationMs: r.timings.duration })}`);
  sleep(1);
}
