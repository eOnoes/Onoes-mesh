Goal: add lib/version.mjs exporting `version` read from package.json, and test/version.test.mjs asserting it matches.
Check: `npm test` passes (29 tests). Commit. Write JOB.md.
Allowed: lib/version.mjs, test/version.test.mjs, test/check.mjs (register the test if needed), package.json, DECISIONS.md.
Do not touch: anything else.
The baseline package.json has no version. Set its initial version to 0.1.0 and record that simple choice in DECISIONS.md.
