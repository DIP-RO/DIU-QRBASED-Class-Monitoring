from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from backend.auth import resolve_or_bootstrap_user
from backend.models import AuditEvent,Role,User

def cfg(email,environment="test"): return SimpleNamespace(bootstrap_admin_email=email,effective_bootstrap_admin_email=email,environment=environment)
def claims(email="first@diu.edu.bd",sub="google-sub-1"): return {"email":email,"sub":sub,"name":"First Administrator"}

def test_configured_identity_bootstraps_exactly_one_admin(db):
    user,created=resolve_or_bootstrap_user(db,claims(),cfg("FIRST@diu.edu.bd"))
    assert created and user.role==Role.SYSTEM_ADMIN
    event=db.scalar(select(AuditEvent).where(AuditEvent.action=="SYSTEM_ADMIN_BOOTSTRAPPED"))
    assert event and event.actor_id==user.id
    same,created_again=resolve_or_bootstrap_user(db,claims(),cfg("first@diu.edu.bd"))
    assert same.id==user.id and not created_again

def test_wrong_email_cannot_bootstrap(db):
    with pytest.raises(HTTPException) as exc:
        resolve_or_bootstrap_user(db,claims("other@diu.edu.bd"),cfg("first@diu.edu.bd"))
    assert exc.value.status_code==403

def test_bootstrap_is_disabled_after_any_system_admin_exists(db):
    db.add(User(provider_subject="existing",email="existing@diu.edu.bd",name="Existing",role=Role.SYSTEM_ADMIN,active=True));db.commit()
    with pytest.raises(HTTPException) as exc:
        resolve_or_bootstrap_user(db,claims(),cfg("first@diu.edu.bd"))
    assert exc.value.status_code==403

def test_development_bootstrap_ignores_only_demo_admin(db):
    db.add(User(provider_subject="demo-admin",email="demo@example.invalid",name="Demo",role=Role.SYSTEM_ADMIN,active=True));db.commit()
    user,created=resolve_or_bootstrap_user(db,claims(),cfg("first@diu.edu.bd","development"))
    assert created and user.email=="first@diu.edu.bd"
