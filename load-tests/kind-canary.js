// Bounded success-only traffic for the existing five-minute canary gates.
import { sleep } from 'k6';
import { checkout as placeOrder, setup, handleSummary } from './checkout.js';
import { integer } from './config.mjs';
export { setup, handleSummary };
const attempts = integer(__ENV.MAX_ATTEMPTS, 30, 1, 30, 'MAX_ATTEMPTS');
export const options = {
  insecureSkipTLSVerify: __ENV.ALLOW_INSECURE_TLS === 'true',
  scenarios: { checkout: { executor: 'shared-iterations', vus: 1,
    iterations: attempts, maxDuration: '25m', exec: 'checkout' } },
  thresholds: { checkout_assertion_failures: ['count==0'] },
};
export function checkout() { placeOrder(); sleep(12); }
