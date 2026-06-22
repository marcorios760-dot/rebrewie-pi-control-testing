"""
app/routers/pages.py – HTML page routes rendered with Jinja2.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ..auth import check_login, clear_session_cookie, current_user, set_session_cookie
from ..machine_registry import load_machine_registration, save_machine_registration
from ..state import brew_state
from ..recipes import list_cleaning_programs, list_recipes
from ..config import settings, COMMAND_MAP

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter()


def _is_remote_request(request: Request) -> bool:
    host = (request.headers.get("x-forwarded-host") or request.url.hostname or "").split(":")[0]
    public_host = settings.remote_public_hostname.strip().lower()
    if public_host and host.lower() == public_host:
        return True
    return host.lower().endswith(".commogrunt.com")


def _context(request: Request, **extra):
    ctx = {
        "request": request,
        "state": brew_state,
        "remote_connected": _is_remote_request(request),
        "remote_hostname": settings.remote_public_hostname or request.headers.get("x-forwarded-host", ""),
        "machine_registration": load_machine_registration(),
        "current_user": current_user(request),
        "auth_enabled": settings.auth_enabled,
    }
    ctx.update(extra)
    return ctx


@router.get("/login", response_class=HTMLResponse)
async def page_login(request: Request, next: str = "/"):
    if settings.auth_enabled and current_user(request):
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        _context(request, next=next, error=""),
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    result = check_login(username, password)
    if not result.ok:
        return templates.TemplateResponse(
            "login.html",
            _context(request, next=next, error=result.reason),
            status_code=401,
        )

    response = RedirectResponse(next or "/", status_code=303)
    set_session_cookie(response, username)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        _context(request, transport=settings.brewie_transport),
    )


@router.get("/progress", response_class=HTMLResponse)
async def page_progress(request: Request):
    return templates.TemplateResponse(
        "progress.html",
        _context(request),
    )


@router.get("/preparation", response_class=HTMLResponse)
async def page_preparation(request: Request):
    return templates.TemplateResponse(
        "preparation.html",
        _context(request, commands=COMMAND_MAP),
    )


@router.get("/cleaning", response_class=HTMLResponse)
async def page_cleaning(request: Request):
    programs = list_cleaning_programs()
    return templates.TemplateResponse(
        "cleaning.html",
        _context(request, programs=programs),
    )


@router.get("/developer", response_class=HTMLResponse)
async def page_developer(request: Request):
    return templates.TemplateResponse(
        "developer.html",
        _context(request, commands=COMMAND_MAP),
    )


@router.get("/recipes", response_class=HTMLResponse)
async def page_recipes(request: Request):
    recipes = list_recipes()
    return templates.TemplateResponse(
        "recipes.html",
        _context(request, recipes=recipes),
    )


@router.get("/recipes/new", response_class=HTMLResponse)
async def page_recipe_new(request: Request):
    return templates.TemplateResponse(
        "recipe_editor.html",
        _context(request, recipe=None, recipe_data=None),
    )


@router.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
async def page_recipe_edit(recipe_id: str, request: Request):
    from ..recipes import load_recipe
    recipe = load_recipe(recipe_id)
    recipe_data = recipe.model_dump() if recipe else None
    return templates.TemplateResponse(
        "recipe_editor.html",
        _context(request, recipe=recipe, recipe_data=recipe_data),
    )


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request, saved: str = ""):
    return templates.TemplateResponse(
        "settings.html",
        _context(request, saved=saved),
    )


@router.post("/settings/machine")
async def update_machine_settings(
    machine_id: str = Form(...),
    label: str = Form("Brewie"),
):
    save_machine_registration(machine_id, label)
    return RedirectResponse("/settings?saved=1", status_code=303)
