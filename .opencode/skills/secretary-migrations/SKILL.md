---
name: secretary-migrations
description: Use when adding or changing a database migration. Covers numbering, forward-only SQL, the migration runner, backup-before-migrate, and repo/test updates.
---
1. Create a new numbered file in `migrations/` (the next number after the highest applied one). Never edit or renumber an applied migration.
2. Write forward-only SQL inside a transaction. Use `PRAGMA foreign_keys = ON`.
3. Add a repo method + tests in `tests/unit/store/` that apply the migration to a temp DB and assert schema/data.
4. Update `docs/adr` and `docs/progress.md` if the schema semantics changed.
5. Run the migration runner on a temp copy before touching any real DB. Backup first.
