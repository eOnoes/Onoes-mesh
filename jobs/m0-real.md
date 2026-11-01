Goal: jobs/inputs/lifecycle12_candidate.json holds two Python sources (ownedJobSource, testSource) for a Windows Job Object process runner. Materialize them as lib/owned_job.py and test/test_owned_job.py, then make `python -m unittest -v test.test_owned_job` pass on this machine. Fix real defects; do not weaken the tests' cleanup/identity assertions.
Check: the unittest command passes; `git status` clean after commit; JOB.md.
Allowed: lib/owned_job.py, test/test_owned_job.py, DECISIONS.md.
Do not touch: anything under D:\tmp; use the staged candidate copy.
A parallel worker owns tools/mesh_dispatch.py and test/test_mesh_dispatch.py; do not edit those files.
Use native Windows Python. JOB.md is permitted for the required job result.
