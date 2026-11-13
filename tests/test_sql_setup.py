"""SQL untuk Supabase SQL Editor: schema + seed idempoten, INSERT admin bisa dipakai login."""

from pathlib import Path

import pytest

from core.repo.postgres import PostgresRepository
from core.security import verify_pin
from scripts.admin_sql import admin_insert_sql
from tests.conftest import PG_TABLES

SEED = (Path(__file__).resolve().parents[1] / "db" / "seed.sql").read_text(encoding="utf-8")


def test_seed_sql_idempotent_and_matches_defaults(pg_db):
    pg_db.run("truncate " + ", ".join(f"absensi.{t}" for t in PG_TABLES) + " restart identity cascade")
    pg_db.migrate()
    with pg_db.tx() as c:
        c.execute(SEED)
    with pg_db.tx() as c:
        c.execute(SEED)  # kedua kali tidak error, tidak menggandakan
    repo = PostgresRepository(db=pg_db)
    assert [d.code for d in repo.meta.list_session_defs()] == ["S1", "S2"]
    assert len(repo.meta.list_items("kelas")) == 8 and len(repo.meta.list_items("mapel")) == 5
    s = repo.settings.get()
    assert s.radius_m == 100 and s.grace_min == 5 and s.lat is None and not s.location_set


def test_admin_insert_sql_logs_in(pg_db):
    pg_db.run("truncate " + ", ".join(f"absensi.{t}" for t in PG_TABLES) + " restart identity cascade")
    sql = admin_insert_sql(" Admin ", "Pak O'Brien", "rahasia123")
    assert "rahasia123" not in sql and "$argon2" in sql
    pg_db.run(sql)
    u = PostgresRepository(db=pg_db).users.get_by_username("admin")
    assert u.role == "admin" and u.name == "Pak O'Brien" and u.active
    assert verify_pin(u.pin_hash, "rahasia123")


def test_admin_insert_sql_validates():
    from core.models import AppError

    with pytest.raises(AppError):
        admin_insert_sql("A!", "x", "123456")
    with pytest.raises(AppError):
        admin_insert_sql("admin", "x", "123")
