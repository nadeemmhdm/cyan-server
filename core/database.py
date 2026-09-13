"""
Cyan Server - Database
SQLite-backed persistence (per spec section 21). One file, real schema,
used by web/, storage/, apps/, security/ modules. No in-memory fakes.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

DATA_DIR = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "cyan.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                             expire_on_commit=False)
Base = declarative_base()


def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


# ---------------------------------------------------------------------------
# Users / Auth
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="admin")  # admin | user
    totp_secret = Column(String, nullable=True)
    totp_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Websites (Web Server module)
# ---------------------------------------------------------------------------

class Website(Base):
    __tablename__ = "websites"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    site_type = Column(String, nullable=False)   # static | node | python | docker
    source_type = Column(String, nullable=False)  # folder | git | docker_image
    source = Column(String, nullable=False)        # path, git URL, or image name
    port = Column(Integer, nullable=False)
    domain = Column(String, nullable=True)          # e.g. mysite.example.com
    env_vars = Column(Text, default="{}")            # JSON-encoded dict
    status = Column(String, default="stopped")        # stopped | running | failed
    pid = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DeploymentEvent(Base):
    __tablename__ = "deployment_events"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"))
    action = Column(String)     # deploy | start | stop | restart
    success = Column(Boolean)
    message = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    website = relationship("Website")


# ---------------------------------------------------------------------------
# Storage (Storage Server module)
# ---------------------------------------------------------------------------

class StorageConfig(Base):
    __tablename__ = "storage_config"
    id = Column(Integer, primary_key=True)
    root_path = Column(String, nullable=False)
    quota_gb = Column(Float, nullable=True)  # None = unlimited


class ShareLink(Base):
    __tablename__ = "share_links"
    id = Column(Integer, primary_key=True)
    token = Column(String, unique=True, nullable=False, index=True)
    relative_path = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Applications (Application Manager module)
# ---------------------------------------------------------------------------

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    app_type = Column(String, nullable=False)   # docker | docker_compose | node | python | static
    manifest_yaml = Column(Text, nullable=False)
    status = Column(String, default="stopped")
    pid = Column(Integer, nullable=True)
    container_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Cloudflare Tunnel
# ---------------------------------------------------------------------------

class TunnelConfig(Base):
    __tablename__ = "tunnel_config"
    id = Column(Integer, primary_key=True)
    provider = Column(String, default="cloudflare")   # cloudflare | ngrok
    tunnel_name = Column(String, nullable=False)
    tunnel_id = Column(String, nullable=True)
    status = Column(String, default="disabled")  # disabled | enabled | error
    created_at = Column(DateTime, default=utcnow)


class TunnelHostname(Base):
    __tablename__ = "tunnel_hostnames"
    id = Column(Integer, primary_key=True)
    tunnel_config_id = Column(Integer, ForeignKey("tunnel_config.id"))
    hostname = Column(String, nullable=False)
    local_service = Column(String, nullable=False)  # e.g. http://localhost:8080


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    event = Column(String, nullable=False)       # login_success | login_failed | login_locked
    username = Column(String, nullable=True)
    source_ip = Column(String, nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class UpdateConfig(Base):
    __tablename__ = "update_config"
    id = Column(Integer, primary_key=True)
    auto_check = Column(Boolean, default=True)
    auto_apply = Column(Boolean, default=False)   # off by default — downloading is safe, auto-applying isn't
    check_interval_minutes = Column(Integer, default=60)
    last_checked_at = Column(DateTime, nullable=True)
    last_check_result = Column(String, nullable=True)  # up_to_date | update_available | error


class TrashItem(Base):
    __tablename__ = "trash_items"
    id = Column(Integer, primary_key=True)
    item_type = Column(String, nullable=False)     # storage | website | database
    original_path = Column(String, nullable=False)  # where it lived (relative, for storage)
    trash_path = Column(String, nullable=False)      # where the content actually is now
    name = Column(String, nullable=False)              # display name
    metadata_json = Column(Text, default="{}")          # type-specific extra info (site config, etc.)
    deleted_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)         # deleted_at + retention period


import random


def generate_unique_id(name: str) -> str:
    """Generates an identifier: name_random4to6digits (e.g., mydb_48291)."""
    clean = "".join(c for c in name.lower().replace("-", "_").replace(" ", "_") if c.isalnum() or c == "_").strip("_")
    if not clean:
        clean = "item"
    rand_num = random.randint(1000, 999999)
    return f"{clean}_{rand_num}"


class ManagedDatabase(Base):
    __tablename__ = "managed_databases"
    id = Column(Integer, primary_key=True)
    unique_id = Column(String, unique=True, nullable=True, index=True)
    name = Column(String, unique=True, nullable=False)
    engine = Column(String, nullable=False)          # sqlite | postgres
    connection_info = Column(Text, nullable=False)     # JSON: path (sqlite) or dsn parts (postgres)
    created_at = Column(DateTime, default=utcnow)


class StorageBucket(Base):
    __tablename__ = "storage_buckets"
    id = Column(Integer, primary_key=True)
    unique_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    permissions = Column(String, default="full")  # full | read | write
    created_at = Column(DateTime, default=utcnow)
    last_used_at = Column(DateTime, nullable=True)


class BackupConfig(Base):
    __tablename__ = "backup_config"
    id = Column(Integer, primary_key=True)
    destination_dir = Column(String, nullable=True)   # None = default (~/.cyan-server/backups)
    retention_count = Column(Integer, default=7)
    interval_hours = Column(Integer, default=24)
    auto_enabled = Column(Boolean, default=True)         # backups are non-destructive, on by default
    include_storage = Column(Boolean, default=False)      # off by default: storage can be large
    last_backup_at = Column(DateTime, nullable=True)
    last_backup_result = Column(String, nullable=True)


def _auto_migrate():
    """Inspects all SQLAlchemy tables against the active SQLite database
    and automatically issues ALTER TABLE ADD COLUMN for any newly added columns.
    Prevents 500 crashes like 'no such column' on schema updates."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if table_name in existing_tables:
                existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
                for col in table.columns:
                    if col.name not in existing_cols:
                        col_type = col.type.compile(engine.dialect)
                        default = ""
                        if col.server_default is not None:
                            default = f"DEFAULT {col.server_default.arg}"
                        elif col.default is not None and not callable(col.default.arg):
                            default = f"DEFAULT '{col.default.arg}'"
                        alter_query = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {default}"
                        conn.execute(text(alter_query))


def init_db():
    Base.metadata.create_all(engine)
    _auto_migrate()
    session = get_session()
    try:
        dbs = session.query(ManagedDatabase).filter(ManagedDatabase.unique_id.is_(None)).all()
        for d in dbs:
            d.unique_id = generate_unique_id(d.name)
        if dbs:
            session.commit()
    finally:
        session.close()


def get_session() -> Session:
    return SessionLocal()
