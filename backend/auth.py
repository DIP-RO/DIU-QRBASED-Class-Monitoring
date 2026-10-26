from authlib.integrations.starlette_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from backend.config import get_settings
from backend.database import get_db
from backend.models import AuditEvent, Role, Teacher, TeacherAlias, User
from backend.security import safe_return_path, utcnow
import secrets
from urllib.parse import quote, urlparse

router=APIRouter(prefix="/auth",tags=["authentication"]); settings=get_settings(); oauth=OAuth()
if settings.google_client_id:
    oauth.register("google",client_id=settings.google_client_id,client_secret=settings.google_client_secret,server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",client_kwargs={"scope":"openid email profile"},code_challenge_method="S256")

def resolve_or_bootstrap_user(db: Session, claims: dict, config=settings) -> tuple[User, bool]:
    """Resolve a mapped OIDC identity or create exactly one configured first admin."""
    email=str(claims["email"]).strip().lower()
    subject=str(claims["sub"])
    user=db.scalar(select(User).where(User.provider_subject==subject,User.email==email,User.active))
    if user:
        return user,False
    bootstrap_email=getattr(config,"effective_bootstrap_admin_email",config.bootstrap_admin_email).strip().lower()
    admin_query=select(func.count()).select_from(User).where(User.role==Role.SYSTEM_ADMIN)
    if getattr(config,"environment","test") == "development":
        admin_query=admin_query.where(~User.provider_subject.startswith("demo-"))
    admin_count=db.scalar(admin_query) or 0
    if not bootstrap_email or email!=bootstrap_email or admin_count:
        raise HTTPException(403,"Account is not mapped or active")
    conflicting=db.scalar(select(User).where((User.email==email)|(User.provider_subject==subject)))
    if conflicting:
        raise HTTPException(409,"Bootstrap identity conflicts with an existing account")
    user=User(provider_subject=subject,email=email,name=str(claims.get("name") or email),role=Role.SYSTEM_ADMIN,department_id=None,active=True)
    db.add(user);db.flush()
    db.add(AuditEvent(actor_id=user.id,action="SYSTEM_ADMIN_BOOTSTRAPPED",target_type="user",target_id=str(user.id),created_at=utcnow(),changes={"email":email,"role":Role.SYSTEM_ADMIN.value},reason="Configured one-time bootstrap identity",correlation_id=secrets.token_hex(16)))
    db.commit()
    return user,True

@router.get("/login")
async def login(request: Request, return_to: str="/"):
    safe_path=safe_return_path(return_to)
    configured=urlparse(settings.public_base_url)
    if request.url.netloc!=configured.netloc:
        canonical=f"{settings.public_base_url.rstrip('/')}/auth/login?return_to={quote(safe_path,safe='/')}"
        return RedirectResponse(canonical,status_code=307)
    request.session["return_to"]=safe_path
    if not settings.google_client_id: raise HTTPException(503,"Google OIDC is not configured")
    return await oauth.google.authorize_redirect(request,settings.public_base_url+"/auth/callback")
@router.get("/callback")
async def callback(request: Request, db: Session=Depends(get_db)):
    try:
        token=await oauth.google.authorize_access_token(request)
        claims=token.get("userinfo") or await oauth.google.parse_id_token(request,token)
    except OAuthError as exc:
        raise HTTPException(400,"Google sign-in session expired or used a different hostname. Start sign-in again from the application URL.") from exc
    if not claims.get("email_verified"): raise HTTPException(403,"Verified email required")
    email=claims["email"].lower(); domain=email.rsplit("@",1)[-1]
    if settings.domains and domain not in settings.domains: raise HTTPException(403,"Institutional account required")
    user,_=resolve_or_bootstrap_user(db,claims)
    return_to=request.session.get("return_to","/")
    request.session.clear(); request.session["user_id"]=user.id
    return RedirectResponse(return_to)
@router.post("/logout")
async def logout(request: Request): request.session.clear(); return {"ok":True}
@router.post("/dev-login/{user_id}")
async def dev_login(user_id:int,request:Request,db:Session=Depends(get_db)):
    if not settings.dev_auth_enabled or settings.environment=="production": raise HTTPException(404)
    if not db.get(User,user_id): raise HTTPException(404,"User not found")
    request.session.clear(); request.session["user_id"]=user_id; return {"ok":True}

@router.get("/dev-users")
async def dev_users(db:Session=Depends(get_db)):
    if not settings.dev_auth_enabled or settings.environment=="production": raise HTTPException(404)
    teachers=db.scalars(select(Teacher).where(Teacher.active).order_by(Teacher.name)).all()
    result=[]
    for teacher in teachers:
        initials=db.scalar(select(TeacherAlias.alias).where(TeacherAlias.teacher_id==teacher.id)) or ""
        result.append({"user_id":teacher.user_id,"teacher_id":teacher.id,"name":f"{initials} · {teacher.name}" if initials else teacher.name,"initials":initials,"department_id":teacher.department_id})
    return result
