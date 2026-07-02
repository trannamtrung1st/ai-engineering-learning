# 1. Agent Loading Order

Load in this order before writing code:

1. `_bmad-output/project-context.md` — global rules
2. `spine/index.md` — invariants (AD-1…AD-15); load section files as needed
3. `_bmad-output/specs/spec-hesd-workshop-attendance/SPEC.md` + `check-in-validation.md` + `roles.md`
4. UX router: `_bmad-output/planning-artifacts/ux-designs/ux-ai-harnessed_hesd-2026-07-02/index.md`
5. Neobrutalism skill: `.agents/skills/neobrutalism-design-system/SKILL.md`

**Quick paths by task:**

| Task | Load |
|------|------|
| Schema / migrations | `spine/9-structural-seed.md` |
| Check-in logic | `spine/3-ad-check-in.md` + spec `check-in-validation.md` |
| Auth / middleware | `spine/4-ad-auth-security.md` |
| API / NestJS scaffold | `spine/2-ad-foundation.md` + `implementation/2-cold-start.md` + `implementation/6-api-surface.md` |
| Docker / local dev | `spine/6-ad-deployment.md` (AD-14) |
| Student UI | UX `experience/10-flow-uj3-trang-checkin.md` |
| QR display | UX `experience/9-flow-uj2-minh-open-session.md` + `spine/3-ad-check-in.md` |
