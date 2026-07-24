# Implement-phase example skill

When implementing a todos-tool item:

1. Read the item checklist and treat it as the execution plan.
2. Mark each finished step `done: true` in the current item YAML.
3. Reorder, add, update, or remove checklist steps in the current item file when scope changes; justify removals in the work summary.
4. To move a step to another item, write `checklist_moves` in `todos/runs/<item-id>/restructure-proposal.json` instead of editing other item files.
5. Do not set item `status` to done or weaken acceptance criteria.

Example restructure fragment:

```json
{
  "schema_version": 1,
  "item_id": "TASK-001",
  "supersede": false,
  "new_items": [],
  "dependency_updates": {},
  "checklist_moves": [
    {"id": "ck-tests", "to_item_id": "TASK-002"}
  ],
  "notes": "Tests belong with the fix item."
}
```
