# Change Requests

Approved phase outputs are frozen. When later work shows that one of them is wrong or incomplete, the agent adds an entry here that names each file or folder to change in backticks, and asks Brandon in chat. If he says yes, the agent records his answer under Decision and makes the change. The phase stays approved. The phase gate lets the agent write a frozen file only once an entry here names it.

Format:

```
### CR-001: Short Title
Raised: 2026-12-03, during Phase 4
Files: `docs/schema/schema.sql`
Problem: ...
Proposed change: ...
Decision: accepted or rejected in chat, date, and Brandon's words
```

## Requests

### CR-001: Versioned Records Replace Undo-by-Deletion
Raised: 2026-11-27, during Phase 2
Files: `docs/spec/spec.md`, `mockups/audit.html`, `mockups/edit.html`
Problem: Q-064 chose versioned rows (valid_from, valid_to, who, why) for the audit history, and reverting writes a new version instead of deleting the entry. The spec says the opposite: AUD-04 "Undo puts the change back and deletes the entry, so the log lists only changes in effect (Q-044)", and HIST-01, HIST-03, EDIT-06 and TFM-08 build on that.
Proposed change: AUD-04 becomes "Restore This Version writes a new version that copies the chosen one, with who and why; nothing is deleted." AUD-02 and HIST-01 to HIST-03 list every version, not only the changes in effect. EDIT-06 and TFM-08 say a deleted record or file is put back by restoring its last version. AUD-05 becomes "Any version can be restored, including one written by the pipeline" (Q-069). The roles table's "Undo of any change" becomes "Restore any version". In `mockups/audit.html`, the Undo button becomes Restore This Version, the notes "Undo puts the old values back and removes this entry from the log" and "Undo the newer change first" are removed, and the subtitle says every change instead of every change in effect.
Decision: accepted in chat, 2026-11-27. Brandon: "Yes, accept CR-001".
Also changed, as consequences of the same change: the overview's "review and undo changes" became "review changes and restore earlier versions"; the out-of-scope line "Keeping undone changes in the audit log (Q-044)" was removed; HIST-02 says each version holds the whole record and field changes come from comparing versions; the pipeline entry in `mockups/audit.html` lost "Change the pipeline rule to reverse this." and gained Restore This Version (AUD-05); `mockups/edit.html` says an earlier version can be restored from the Audit Log instead of "undone".
