# Tests

Pull the live data first (only the second set needs it):

```
ops/pull-db.sh                  # Windows: ops\pull-db.ps1
```

CI tests, no database, the same ones CI runs:

```
ops/test.sh unit                # Windows: ops\test.ps1 unit
```

Everything else, against a copy of your local database:

```
ops/test.sh reference           # Windows: ops\test.ps1 reference
```

Both: `ops/test.sh all`.
