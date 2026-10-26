import hashlib, ipaddress, secrets
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import NetworkRule, Role, User

def utcnow(): return datetime.now(timezone.utc)
def token_hash(token: str): return hashlib.sha256(token.encode()).hexdigest()
def opaque_token(): return secrets.token_urlsafe(32)
def safe_return_path(value: str|None): return value if value and value.startswith("/") and not value.startswith("//") else "/"

def current_user(request: Request, db: Session=Depends(get_db)) -> User:
    uid=request.session.get("user_id")
    user=db.get(User, uid) if uid else None
    if not user or not user.active: raise HTTPException(401,"Authentication required")
    return user

def require_roles(*roles):
    def dependency(user: User=Depends(current_user)):
        if user.role not in roles: raise HTTPException(403,"Insufficient role")
        return user
    return dependency

def resolve_client_ip(request: Request, rules: list[NetworkRule]) -> str:
    peer=request.client.host if request.client else ""
    proxies=[ipaddress.ip_network(r.cidr) for r in rules if r.is_trusted_proxy]
    try: trusted=any(ipaddress.ip_address(peer) in n for n in proxies)
    except ValueError: trusted=False
    if trusted:
        chain=[x.strip() for x in request.headers.get("x-forwarded-for","").split(",") if x.strip()]
        for candidate in reversed(chain):
            try:
                addr=ipaddress.ip_address(candidate)
                if not any(addr in n for n in proxies): return str(addr)
            except ValueError: continue
    return peer

def network_allowed(address: str, rules: list[NetworkRule]):
    try: ip=ipaddress.ip_address(address)
    except ValueError: return False
    return any(not r.is_trusted_proxy and ip in ipaddress.ip_network(r.cidr) for r in rules)

def validate_cidr(cidr: str):
    network=ipaddress.ip_network(cidr, strict=True)
    if network.prefixlen == 0: raise ValueError("Allow-all networks are forbidden")
    return str(network)

