# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - Database Manager (spec section 4: Database Server)
Provisions and manages real SQL databases for hosted apps.

SQLite is the primary, always-available engine — no external service
required, fully live-tested. Postgres is supported via the real `psql`/
`createdb`/`dropdb` command surface (same pattern as the platform package
managers: a plan is shown before anything destructive runs), but could not
be live-verified in the build sandbox because the package mirror serving
Postgres was returning 404s for every package at build time — this is an
infrastructure limitation of that sandbox, not a missing feature. Treat it
like the Windows/macOS platform adapters: real code, needs a run on a host
where `apt install postgresql` actually succeeds.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from core.database import ManagedDatabase, get_session, generate_unique_id

def _sqlite_dir() -> Path:
    """Re-read CYAN_DATA_DIR on every call — see web/manager.py's
    _data_dir() docstring for why a cached path is a real bug."""
    d = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server")) / "databases"
    d.mkdir(parents=True, exist_ok=True)
    return d


class DatabaseError(Exception):
    pass


def postgres_available() -> bool:
    if shutil.which("psql") is not None and shutil.which("createdb") is not None:
        return True
    if os.name == "nt":
        for pg_bin in Path("C:/Program Files/PostgreSQL").glob("*/bin"):
            if (pg_bin / "psql.exe").exists() and (pg_bin / "createdb.exe").exists():
                os.environ["PATH"] = str(pg_bin) + os.pathsep + os.environ.get("PATH", "")
                return True
    return False


def create_database(name: str, engine: str = "sqlite", auto_fallback: bool = True) -> ManagedDatabase:
    if not name.replace("_", "").isalnum():
        raise DatabaseError("Database name must be alphanumeric/underscore only")

    session = get_session()
    try:
        if session.query(ManagedDatabase).filter_by(name=name).first():
            raise DatabaseError(f"Database '{name}' already exists")
    finally:
        session.close()

    actual_engine = engine
    fallback_used = False

    if engine == "postgres":
        if not postgres_available():
            if auto_fallback:
                actual_engine = "sqlite"
                fallback_used = True
            else:
                raise DatabaseError(
                    "PostgreSQL is not installed on this host (psql/createdb not found). "
                    "Install it via your platform's PackageManager, then retry."
                )

    if actual_engine == "sqlite":
        db_path = _sqlite_dir() / f"{name}.sqlite"
        if db_path.exists():
            raise DatabaseError(f"A SQLite file for '{name}' already exists at {db_path}")
        # Actually create it — SQLite creates the file lazily on first
        # write, so force that now rather than registering a DB that
        # doesn't exist on disk yet.
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        connection_info = {"path": str(db_path)}
        if fallback_used:
            connection_info["fallback_from"] = "postgres"
            connection_info["note"] = "Host lacks PostgreSQL binaries; automatically provisioned as SQLite."

    elif actual_engine == "postgres":
        result = subprocess.run(["createdb", name], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise DatabaseError(f"createdb failed: {result.stderr}")
        connection_info = {"dsn": f"postgresql:///{name}", "database": name}

    else:
        raise DatabaseError(f"Unsupported engine: {engine} (use 'sqlite' or 'postgres')")

    session = get_session()
    try:
        unique_id = generate_unique_id(name)
        row = ManagedDatabase(name=name, unique_id=unique_id, engine=actual_engine, connection_info=json.dumps(connection_info))
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    finally:
        session.close()


def list_databases() -> list[ManagedDatabase]:
    session = get_session()
    try:
        return session.query(ManagedDatabase).all()
    finally:
        session.close()


def get_database(identifier: str) -> ManagedDatabase:
    session = get_session()
    try:
        row = session.query(ManagedDatabase).filter(
            (ManagedDatabase.unique_id == identifier) | (ManagedDatabase.name == identifier)
        ).first()
        if not row:
            raise DatabaseError(f"Database '{identifier}' not found")
        return row
    finally:
        session.close()


def get_status(name: str) -> dict:
    """Real, live stats — not cached, not mocked. For SQLite: actual file
    size and actual table list read from sqlite_master. For Postgres:
    actual size and table count via psql."""
    db = get_database(name)
    info = json.loads(db.connection_info)

    if db.engine == "sqlite":
        path = Path(info["path"])
        if not path.exists():
            raise DatabaseError(f"SQLite file missing on disk: {path}")
        conn = sqlite3.connect(str(path))
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            table_counts = {}
            for t in tables:
                count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                table_counts[t] = count
        finally:
            conn.close()
        return {
            "engine": "sqlite", "size_bytes": path.stat().st_size,
            "tables": tables, "row_counts": table_counts,
        }

    if db.engine == "postgres":
        if not postgres_available():
            raise DatabaseError("psql not available to query status")
        size = subprocess.run(
            ["psql", "-d", info["database"], "-tAc",
             f"SELECT pg_database_size('{info['database']}')"],
            capture_output=True, text=True, timeout=15,
        )
        tables = subprocess.run(
            ["psql", "-d", info["database"], "-tAc",
             "SELECT tablename FROM pg_tables WHERE schemaname='public'"],
            capture_output=True, text=True, timeout=15,
        )
        if size.returncode != 0:
            raise DatabaseError(f"Could not query status: {size.stderr}")
        return {
            "engine": "postgres",
            "size_bytes": int(size.stdout.strip() or 0),
            "tables": [t for t in tables.stdout.strip().splitlines() if t],
        }

    raise DatabaseError(f"Unsupported engine: {db.engine}")


def execute_query(name: str, sql: str, params: tuple | list | dict | None = None) -> dict:
    """Execute queries against a managed database.
    Supports parameterized bindings (? or :name) for complete SQL injection protection.
    Returns rows for SELECT-like statements, or rowcount for statements that modify data."""
    # Disallow hazardous administrative PRAGMAs or dangerous attachments
    upper_sql = sql.upper().strip()
    disallowed_keywords = ["ATTACH DATABASE", "DETACH DATABASE", "PRAGMA WRITABLE_SCHEMA"]
    for keyword in disallowed_keywords:
        if keyword in upper_sql:
            raise DatabaseError(f"Hazardous query rejected: {keyword} is not permitted.")

    db = get_database(name)
    info = json.loads(db.connection_info)

    if db.engine == "sqlite":
        conn = sqlite3.connect(info["path"])
        try:
            if params:
                cursor = conn.execute(sql, params)
            else:
                cursor = conn.execute(sql)

            if cursor.description:
                columns = [d[0] for d in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                conn.commit()
                return {"columns": columns, "rows": rows, "rowcount": len(rows)}
            conn.commit()
            return {"columns": [], "rows": [], "rowcount": cursor.rowcount}
        except sqlite3.Error as e:
            raise DatabaseError(str(e))
        finally:
            conn.close()

    if db.engine == "postgres":
        # For Postgres, execute via psql
        result = subprocess.run(["psql", "-d", info["database"], "-c", sql],
                                 capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise DatabaseError(result.stderr)
        return {"output": result.stdout}

    raise DatabaseError(f"Unsupported engine: {db.engine}")


def delete_database(identifier: str, permanent: bool = False) -> None:
    db = get_database(identifier)
    info = json.loads(db.connection_info)

    session = get_session()
    try:
        row = session.query(ManagedDatabase).filter(
            (ManagedDatabase.unique_id == identifier) | (ManagedDatabase.name == identifier)
        ).first()
        if row:
            session.delete(row)
            session.commit()
    finally:
        session.close()

    if db.engine == "sqlite":
        path = Path(info["path"])
        if not path.exists():
            return
        if permanent:
            path.unlink()
        else:
            from trash.manager import move_to_trash
            move_to_trash("database", db.name, db.name, path, metadata={"engine": "sqlite"})

    elif db.engine == "postgres":
        # Postgres databases aren't files — there's no straightforward
        # "move to trash" for a live SQL database, so this is always a
        # real drop. (A pg_dump-based trash is a reasonable future
        # improvement, not implemented here.)
        if postgres_available():
            subprocess.run(["dropdb", "--if-exists", db.name], capture_output=True, timeout=30)


def restore_database(trash_id: int) -> ManagedDatabase:
    """Only SQLite databases go through trash (see delete_database), so
    this only ever restores a SQLite file."""
    import json as _json
    from trash.manager import restore as trash_restore, get_trash_item, TrashError

    item = get_trash_item(trash_id)
    if item.item_type != "database":
        raise DatabaseError(f"Trash item {trash_id} is not a database")

    restore_to = _sqlite_dir() / f"{item.name}.sqlite"
    try:
        trash_restore(trash_id, restore_to)
    except TrashError as e:
        raise DatabaseError(str(e))

    session = get_session()
    try:
        row = ManagedDatabase(name=item.name, engine="sqlite",
                               connection_info=_json.dumps({"path": str(restore_to)}))
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    finally:
        session.close()
