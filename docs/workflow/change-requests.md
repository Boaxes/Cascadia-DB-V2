# Change Requests

Approved phase outputs are frozen. When later work shows that one of them is wrong or incomplete, the agent adds an entry here and asks Brandon. If he agrees, he reopens the phase (see APPROVALS.md), the change is made, and he approves the phase again.

Format:

```
### CR-001: Short Title
Raised: 2026-12-03, during Phase 4
Frozen document: docs/schema/schema.sql
Problem: ...
Proposed change: ...
Decision: (Brandon) accepted / rejected, date
```

## Requests

### CR-001: Versioned Records Replace Undo-by-Deletion
Raised: 2026-11-27, during Phase 2
Frozen document: docs/spec/spec.md
Problem: Q-064 chose versioned rows (valid_from, valid_to, who, why) for the audit history, and reverting writes a new version instead of deleting the entry. The spec says the opposite: AUD-04 "Undo puts the change back and deletes the entry, so the log lists only changes in effect (Q-044)", and HIST-01, HIST-03, EDIT-06 and TFM-08 build on that.
Proposed change: AUD-04 becomes "Restore This Version writes a new version that copies the chosen one, with who and why; nothing is deleted." AUD-02 and HIST-01 to HIST-03 list every version, not only the changes in effect. EDIT-06 and TFM-08 say a deleted record or file is put back by restoring its last version. AUD-05 follows the answer to the round 2 question on pipeline versions.
Decision:
