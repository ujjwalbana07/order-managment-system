# First prompt to paste into Codex (VS Code)

Put these files in an empty project folder first: AGENTS.md, SPEC.md, golden_cases.json, seed/.

---

Read AGENTS.md and SPEC.md completely, then read golden_cases.json.

Do Milestone M0 only:
1. Scaffold the Django project with the apps listed in AGENTS.md.
2. Create all models from SPEC section 3 with the constraints listed, plus migrations.
3. Implement `core/costing.py` exactly per SPEC section 4 using Decimal only.
4. Write `tests/test_costing_golden.py` that loads golden_cases.json and asserts exact equality for every calc case.
5. Write model-level tests for the constraints (unique account+sales_no, net_wt > 0, negative money rejected).
6. Run pytest and show me the output.

Do not build any screens yet. When M0 is green, give me a short report: what you built, what passes,
and any assumptions you made. Then wait for me to say "go M1".

---

Then for each next milestone, send: `go M1`, `go M2`, and so on. Paste the test output back if anything fails.
