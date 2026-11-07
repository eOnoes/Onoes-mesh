# Mind: selected task context

The first source is the existing Mesh Workroom store. In Mind, the admitted owner
chooses a saved task and deliberately requests Read selected task. Listing the
available titles does not retrieve a separate personal-memory database. The view
uses the same guarded Workroom GET as the task board, with no new credentials,
listener, search service, dispatch, scheduler or memory-writing endpoint.

The selected snapshot displays task ID, project, task/brief/progress revisions,
task update time and retrieval time, description, goal, checklist, result,
evidence references, saved stage, recorded decision and reviewer label. Recorded
results and labels are not independently verified facts. Open source task in
Workroom exposes the existing complete report/review provenance. No transcript,
assignment payload, external chat history or personal profile is copied here.
Source text is rendered as text; references do not execute or fetch anything.

Records from different tasks remain separate; Mind does not merge conflicts or
turn an old approval into approval of a newer revision. The view is a snapshot,
not a live assertion of agent or model state. Selecting another task or refreshing
the app clears it and requires another deliberate read. Failed, mismatched and
late responses cannot repopulate a cleared view.

No additional persisted memory is created. Clear this view removes the displayed
RAM copy, not the source task. Existing Workroom retention/deletion and backups
continue to own that record. Session lock, expiry, offline/page privacy clearance
clear context and title options through the existing application lifecycle.

External memory adapters, personal memory, cross-channel search, automatic writes,
conflict resolution and separate deletion/retention policies require their own
selected source and scope. This initial task-record reader does not qualify them.
