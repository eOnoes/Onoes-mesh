Goal: repair one measured M0 host check failure, preserving the completed m0-real implementation.
This worktree starts at job/m0-real (10c47f36cad5e80bbdd96de9f2bd0ee75cfb6eed).
Host native Python loads its stdlib test package instead of the local namespace directory, so the required command cannot import test.test_owned_job.
Independent discovery passed the unchanged six tests, zero skipped; this is not named-command acceptance.
Add the minimal local test/__init__.py so the repository test package wins normal import resolution.
Check: native Windows python -m unittest -v test.test_owned_job passes all six tests, zero skipped.
Also run named test.test_mesh_runner (13 tests), using Hermes site-packages for psutil if needed, and npm test (29 tests); git diff --check.
Use C:/Users/eMitchell109/AppData/Local/Python/pythoncore-3.14-64/python.exe or another available native Windows interpreter explicitly. Do not change PATH globally.
Run an additional 30 iterations of the retained-descendant test and retain its identity/cleanup assertions unchanged.
Record interpreter and complete named check results in JOB.md. Host runner commits if sandbox Git metadata is denied.
Allowed: test/__init__.py, DECISIONS.md, JOB.md only.
Do not touch: lib/owned_job.py, test/test_owned_job.py, tools/mesh_runner.py, tools/mesh_dispatch.py, other worktrees, milestones, scheduler state, global settings, D:/tmp or unrelated projects.
Do not rematerialize the candidate or weaken any tests; the completed source is already present.
If the minimal package fix reveals another actual defect, report exact evidence in JOB.md instead of expanding scope.
