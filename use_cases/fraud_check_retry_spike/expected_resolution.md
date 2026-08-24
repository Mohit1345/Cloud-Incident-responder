# Expected Resolution: Fraud Check Retry Traffic Spike

## Incident Summary
| Field | Value |
|-------|-------|
| Alarm | fraud-check-request-rate-high |
| Service | fraud-check-service |
| Severity | High |
| Category | Traffic Spike |
| Detected | 2026-08-24T16:45:00Z |

## Root Cause
`payment-service` deployment `v2.14.3` at 16:38 UTC changed `fraud_check.retry.max_attempts`
from **1 → 3**, multiplying effective fraud-check call volume by **~4.5x** (4520 RPM vs 1000 baseline).

## Remediation Applied
- **Action:** Revert `fraud_check.retry.max_attempts` to `1` on payment-service
- **Risk Level:** Low
- **Approval:** Auto-approved (config revert to last known good)

## Expected Outcome
Traffic on fraud-check-service should return to baseline (~1000 RPM) within 5 minutes.
Alarm should transition from ALARM → OK.
