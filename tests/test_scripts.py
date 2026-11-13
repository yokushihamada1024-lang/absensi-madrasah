import pytest

from core.models import AppError
from core.repo.memory import InMemoryRepository
from core.security import verify_pin
from scripts.create_admin import create_admin


def test_create_admin():
    repo = InMemoryRepository()
    u = create_admin(repo, " Admin ", "Pak Admin", "123456")
    assert u.username == "admin" and u.role == "admin"
    assert verify_pin(repo.users.get(u.user_id).pin_hash, "123456")
    assert not verify_pin(u.pin_hash, "654321")
    with pytest.raises(AppError) as e:
        create_admin(repo, "admin", "Lagi", "123456")
    assert e.value.code == "USERNAME_TAKEN"
    with pytest.raises(AppError) as e:
        create_admin(repo, "admin2", "x", "123")
    assert e.value.code == "INVALID_PIN"


def test_verify_pin_unknown_user_is_false():
    assert verify_pin(None, "123456") is False
    assert verify_pin("bukan-hash", "123456") is False


def test_simulate_day_runs(capsys):
    from scripts.simulate_day import main

    assert main() == 0
    assert "Smoke test OK" in capsys.readouterr().out
