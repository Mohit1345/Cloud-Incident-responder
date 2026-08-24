# Runbook: Fraud Check Traffic Spike

## Symptoms
- CloudWatch alarm `fraud-check-request-rate-high` in ALARM state
- RequestCount on `fraud-check-tg` exceeds 4x baseline
- Elevated latency and 5xx on fraud-check-service
- No fraud-check-service deployment in last 2 hours

## Investigation Steps
1. Confirm spike timing and magnitude via CloudWatch metrics
2. Check upstream callers — payment-service is primary client
3. Review recent payment-service deployments and config diffs
4. Look for retry policy or timeout changes affecting call volume

## Root Cause (Common)
Config change to `fraud_check.retry.max_attempts` in payment-service increases
effective call volume to fraud-check-service without a corresponding capacity change.

## Remediation
### Option A — Config revert (preferred, low risk)
Revert `fraud_check.retry.max_attempts` to previous value (typically 1).
Expected traffic normalization within 2-5 minutes.

### Option B — Scale fraud-check-service (higher cost, temporary)
Increase fraud-check-service replica count. Use only if config revert is blocked.

## Rollback Command
```
kubectl set env deployment/payment-service FRAUD_CHECK_RETRY_MAX_ATTEMPTS=1
# or revert via config service to previous snapshot
```

## Verification
- RequestCount on fraud-check-tg returns to ~1000 RPM within 5 min
- TargetResponseTime p99 < 200ms
- Alarm transitions to OK

## Escalation
If traffic does not normalize within 10 minutes after config revert, page #payments-oncall.
