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


def init_db():
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
