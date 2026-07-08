# app/main.py
# Standalone sales dashboard — login gate (คัดจาก ssincom_bill/app/main.py)
# + serve frontend แบบ auth-gated (pattern จาก ssincom_landingpage/backend/main.py)
# + endpoint ข้อมูลสดจาก bill DB (app/sales_dashboard.py)
from __future__ import annotations

import os
from hmac import compare_digest
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .sales_dashboard import router as sales_router

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

FRONTEND_DIR = ROOT_DIR / "frontend"

APP_USER = os.getenv("APP_USER", "admin")
APP_PASS = os.getenv("APP_PASS", "change-me")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-long-random-secret")

app = FastAPI(title="S&S Incom Sales Dashboard")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60 * 60 * 2)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _current_user(request: Request) -> dict | None:
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def _is_safe_next(next_path: str | None) -> bool:
    return bool(next_path and next_path.startswith("/") and not next_path.startswith("//"))


def _safe_next(next_path: str | None, default: str = "/frontend/") -> str:
    return next_path if _is_safe_next(next_path) else default


def _login_redirect(next_path: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={quote(next_path)}", status_code=303)


# --------------------------------------------------------------------------- #
# auth routes
# --------------------------------------------------------------------------- #
@app.get("/login", include_in_schema=False)
async def login_page(request: Request) -> Response:
    next_path = _safe_next(request.query_params.get("next"), "/frontend/")
    if _current_user(request):
        return RedirectResponse(url=next_path, status_code=303)
    return FileResponse(FRONTEND_DIR / "login.html")


@app.post("/login", include_in_schema=False)
async def do_login(request: Request) -> RedirectResponse:
    form = await request.form()
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    next_path = _safe_next(str(form.get("next") or ""), "/frontend/")

    if compare_digest(username, APP_USER) and compare_digest(password, APP_PASS):
        request.session["user"] = {"name": username}
        return RedirectResponse(url=next_path, status_code=303)
    return RedirectResponse(url=f"/login?error=1&next={quote(next_path)}", status_code=303)


@app.get("/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url=_safe_next(request.query_params.get("next"), "/login"), status_code=303)


@app.get("/api/auth/me", include_in_schema=False)
async def auth_me(request: Request) -> dict:
    user = _current_user(request)
    return {"authenticated": bool(user), "user": user}


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/frontend/")


@app.get("/frontend", include_in_schema=False)
async def frontend_without_slash() -> RedirectResponse:
    return RedirectResponse(url="/frontend/")


@app.get("/frontend/", include_in_schema=False)
async def frontend_index(request: Request) -> Response:
    if not _current_user(request):
        return _login_redirect("/frontend/")
    return FileResponse(FRONTEND_DIR / "sand_dashboard.html")


@app.get("/frontend/sand_dashboard.html", include_in_schema=False)
async def sand_dashboard(request: Request) -> Response:
    if not _current_user(request):
        return _login_redirect("/frontend/sand_dashboard.html")
    return FileResponse(FRONTEND_DIR / "sand_dashboard.html")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"ok": True}


# data API (auth-gated ภายใน router)
app.include_router(sales_router)

# static ท้ายสุด (หลัง explicit routes) — เสิร์ฟ asset สาธารณะ เช่น app.js
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
