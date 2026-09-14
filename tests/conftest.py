# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Restores real per-module database/data-dir isolation.

pytest imports (collects) every test module before running any test
function's body. Several test modules here set os.environ["CYAN_DATA_DIR"]
and call core.database.configure() at *import* time, which is fine when a
file is run on its own -- but two things are process-global, not
per-module:

1. core.database's SQLAlchemy engine (whichever module is collected
   *last* silently "wins" the engine for the whole session).
2. os.environ["CYAN_DATA_DIR"] itself -- also left holding whatever the
   last-collected module set, for the rest of the run. Code that reads
   the env var directly at call time (e.g. backup/manager.py's
   _data_dir() helper, and these same test files' own helpers) picks up
   the WRONG module's directory during other modules' test runs, even
   after the engine has been correctly reconfigured -- silently writing
   one test module's files into another's directory.

Each affected module stores the directory it configured as
`_TEST_DATA_DIR`. This fixture re-applies that module's own directory --
both the env var and the engine -- immediately before its tests actually
run (not at collection time), so execution order matches the isolation
the modules were written to expect.
"""
import os

import pytest


@pytest.fixture(autouse=True, scope="module")
def _reconfigure_database_for_this_module(request):
    data_dir = getattr(request.module, "_TEST_DATA_DIR", None)
    if data_dir:
        os.environ["CYAN_DATA_DIR"] = data_dir
        import core.database as core_db
        core_db.configure(data_dir)
        core_db.init_db()
    yield
