import http from 'k6/http';
import { check, sleep } from 'k6';

const base = __ENV.FINESSE_BASE_URL || 'http://127.0.0.1:8600';
export const options = {
  vus: 35,
  duration: '2m',
  thresholds: {
    http_req_duration: ['p(95)<300', 'p(99)<600'],
    http_req_failed: ['rate<0.005'],
  },
};

export default function () {
  const health = http.get(`${base}/healthz`, { tags: { kind: 'non_llm' } });
  check(health, { 'liveness returns 200': (response) => response.status === 200 });
  const ready = http.get(`${base}/readyz`, { tags: { kind: 'non_llm' } });
  check(ready, { 'readiness returns 200': (response) => response.status === 200 });
  sleep(1);
}
