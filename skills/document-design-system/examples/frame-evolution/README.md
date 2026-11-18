# Frame evolution example (fictional)

- `revision-proposal.ttl` — a DeliberationRevision-v1 document: evaluations under DecisionRecord-v1
  could not judge coverage without a stated scope, so it proposes requiring Scope and Criterion
  (accepted). The critique "also require counterarguments" is deferred and carried by an
  UnresolvedIssue. Built with `generated/build_deliberation.py`.
- `decision-record-v2.ttl` — the resulting `frame:DecisionRecord-v2` (`prov:wasRevisionOf` v1).
  v1 is not edited. Load it with `--extra`.

```bash
python3 scripts/evaluate.py doc.ttl --earl before.ttl
python3 scripts/evaluate.py doc-pinned-to-v2.ttl --extra examples/frame-evolution/decision-record-v2.ttl --earl after.ttl
python3 scripts/compare.py before.ttl after.ttl
```
