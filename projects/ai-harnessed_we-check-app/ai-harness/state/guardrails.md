# Harness guardrails

Verification failures and remediation notes for harness agents.
- [AC-04] Test case validation failed — see 20260628T172128Z-testgen.txt
- [AC-13] Test case validation failed — see 20260628T173849Z-testgen.txt
- [AC-13] Test case validation failed — see 20260628T174010Z-testgen.txt
- [NFR-01] Test case validation failed — see 20260628T183306Z-testgen.txt
- [NFR-07] Test case validation failed — see 20260628T184242Z-testgen.txt
- [NFR-11] Test case validation failed — see 20260628T184941Z-testgen.txt
- [NFR-15] Test case validation failed — see 20260628T185520Z-testgen.txt
- [NFR-16] Test case validation failed — see 20260628T185943Z-testgen.txt
- [NFR-17] Test case validation failed — see 20260628T190253Z-testgen.txt
- [NFR-20] Test case validation failed — see 20260628T191006Z-testgen.txt
- [domain-package] Computational checks failed — see 20260628T192740Z-checks.json
- [api-foundation] Computational checks failed — see 20260628T193455Z-checks.json
- [module-session-management] Computational checks failed — see 20260628T200826Z-checks.json
- [module-attendance] Computational checks failed — see 20260628T203417Z-checks.json
- [module-checkin-qr] Computational checks failed — see 20260628T205057Z-checks.json
- [module-reporting-export] Computational checks failed — see 20260628T210529Z-checks.json
- [module-reporting-export] AI review failed — see 20260628T211228Z-review.json
- [web-design-system-shell] Browser test failed — see 20260628T212831Z-browser-test.json
- [web-design-system-shell] Browser test failed — see 20260628T213809Z-browser-test.json

## Signs

- **Sonner toast + React StrictMode:** Do not guard session-expired (or bootstrap) toasts with a `useRef` "shown once" flag. StrictMode remounts `<Toaster />` and drops the first toast; the ref blocks the second `toast.error` call. Use `toast.error(..., { id })` and defer with `setTimeout(0)` in `useEffect` so the toast fires after the remount.
- **Preview seed idempotency:** Do not gate `runPreviewSeed` on a policy_settings marker alone — integration tests truncate auth tables but can leave `preview_seed_version` set, causing browser gates to skip seed and miss deactivated/student fixtures. Verify fixture rows (e.g. `deactivated@example.edu.vn`) exist before skipping.
- [web-design-system-shell] Browser test failed — see 20260628T215822Z-browser-test.json
