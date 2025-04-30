# Old script symlinks

This is where scripts used to live, but they now live under `tubular/scripts/`
(and are installed as entry points via `setup.cfg`), and the symlinks point to
the new locations to aid in migration.

No new files should be added here, and old symlinks should be deleted once all
callers have been updated to use the correct location.
