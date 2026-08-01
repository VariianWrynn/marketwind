"""The migration runner must not report success when it found nothing to apply.

`MIGRATIONS_DIR` is resolved by walking up from __file__, which lands on
/app/migrations in-container only because `python -m` puts the working directory
first on sys.path. Any shift in resolution empties the glob — and an exit-0 there
would let the compose gate (docker-compose.yml `migrate`) bless an empty database.
"""

import pytest

from marketwind.storage import migrate


def test_pending_paths_raises_when_migrations_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with pytest.raises(RuntimeError):
        migrate.pending_migration_paths()


def test_pending_paths_raises_when_migrations_dir_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path / "nope")
    with pytest.raises(RuntimeError):
        migrate.pending_migration_paths()


def test_pending_paths_returns_the_real_migrations_in_filename_order():
    paths = migrate.pending_migration_paths()
    names = [p.name for p in paths]
    assert names, "the repo ships migrations; an empty result here is the bug above"
    assert names == sorted(names)
    assert all(n.endswith(".sql") for n in names)
