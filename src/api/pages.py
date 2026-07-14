"""HTML page routes for the weight configuration UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from src.models.database import Requirement, Role, WeightConfiguration, WeightItem, get_db
from src.services.json_export import export_config_to_json, delete_json_config

router = APIRouter(tags=["pages"])

# Jinja2 environment with template caching disabled (workaround for Python 3.14 + Starlette)
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    cache_size=0,
)


def _render(template_name: str, context: Dict[str, Any]) -> HTMLResponse:
    """Render a Jinja2 template and return an HTMLResponse."""
    template = _jinja_env.get_template(template_name)
    html = template.render(**context)
    return HTMLResponse(content=html)


@router.get("/", response_class=RedirectResponse)
def home(request: Request) -> RedirectResponse:
    """Redirect root to the rankings dashboard."""
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    """Candidate ranking dashboard page."""
    return _render("dashboard.html", {"request": request})


@router.get("/candidate/{candidate_id}", response_class=HTMLResponse)
def candidate_page(request: Request, candidate_id: str) -> HTMLResponse:
    """Candidate detail and chat page."""
    return _render("candidate.html", {"request": request, "candidate_id": candidate_id})


@router.get("/recruiter", response_class=HTMLResponse)
def recruiter_page(request: Request) -> HTMLResponse:
    """Recruiter onboarding wizard — 6-step JD → REQ → Sub-query → Weights → Resumes → Run."""
    return _render("recruiter.html", {"request": request})


@router.get("/configure", response_class=HTMLResponse)
def configure_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Weight configuration page."""
    roles = db.query(Role).all()
    return _render("configure.html", {"request": request, "roles": roles})


@router.get("/api/htmx/roles", response_class=HTMLResponse)
def htmx_roles_list(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """HTMX endpoint to get roles list as HTML."""
    roles = db.query(Role).all()
    return _render("partials/roles_list.html", {"request": request, "roles": roles})


@router.get("/api/htmx/requirements/{role_id}", response_class=HTMLResponse)
def htmx_requirements_form(
    request: Request,
    role_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """HTMX endpoint to get requirements form as HTML."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        return _render("partials/error.html", {"request": request, "error": "Role not found"})

    requirements = db.query(Requirement).filter(Requirement.role_id == role_id).all()

    # Group by category
    categorized: Dict[str, list] = {}
    for req in requirements:
        if req.category not in categorized:
            categorized[req.category] = []
        categorized[req.category].append(req)

    return _render(
        "partials/requirements_form.html",
        {
            "request": request,
            "role": role,
            "requirements": requirements,
            "categorized": categorized,
        },
    )


@router.get("/api/htmx/validate/{role_id}", response_class=HTMLResponse)
def htmx_validate_weights(
    request: Request,
    role_id: int,
    weights: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """HTMX endpoint to validate weights and return validation summary."""
    # Parse weights from query string (format: req_id=weight,req_id=weight)
    weight_map: Dict[int, float] = {}
    if weights:
        for pair in weights.split(","):
            if "=" in pair:
                req_id, weight = pair.split("=", 1)
                try:
                    weight_map[int(req_id)] = float(weight)
                except ValueError:
                    continue

    # Get requirements
    requirements = db.query(Requirement).filter(Requirement.role_id == role_id).all()

    # Calculate totals
    total_allocated = sum(weight_map.values())
    remaining = 100.0 - total_allocated
    is_valid = abs(total_allocated - 100.0) < 0.01

    # Group by category
    categorized: Dict[str, Dict[str, Any]] = {}
    for req in requirements:
        if req.category not in categorized:
            categorized[req.category] = {"total": 0.0, "count": 0, "rated": 0, "unrated": 0}
        categorized[req.category]["count"] += 1
        if req.id in weight_map:
            categorized[req.category]["total"] += weight_map[req.id]
            categorized[req.category]["rated"] += 1
        else:
            categorized[req.category]["unrated"] += 1

    # Add remaining per category
    for cat_data in categorized.values():
        cat_data["remaining"] = 100.0 - cat_data["total"]

    # Items without weight
    unrated_items = [req for req in requirements if req.id not in weight_map]
    rated_items = [req for req in requirements if req.id in weight_map]

    return _render(
        "partials/validation_summary.html",
        {
            "request": request,
            "total_allocated": total_allocated,
            "remaining": remaining,
            "is_valid": is_valid,
            "categorized": categorized,
            "unrated_items": unrated_items,
            "rated_items": rated_items,
            "total_requirements": len(requirements),
            "rated_count": len(rated_items),
            "unrated_count": len(unrated_items),
        },
    )


@router.post("/api/htmx/save/{role_id}", response_class=HTMLResponse)
def htmx_save_weights(
    request: Request,
    role_id: int,
    config_name: str = Form("Default Config"),
    weights: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """HTMX endpoint to save weight configuration."""
    # Parse weights from query string
    weight_map: Dict[int, float] = {}
    if weights:
        for pair in weights.split(","):
            if "=" in pair:
                req_id, weight = pair.split("=", 1)
                try:
                    weight_map[int(req_id)] = float(weight)
                except ValueError:
                    continue

    # Get requirements
    requirements = db.query(Requirement).filter(Requirement.role_id == role_id).all()

    # Validate
    total_allocated = sum(weight_map.values())
    if abs(total_allocated - 100.0) > 0.01:
        return _render(
            "partials/error.html",
            {"request": request, "error": f"Total must be 100%, currently {total_allocated:.1f}%"},
        )

    # Create or update configuration
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        return _render(
            "partials/error.html",
            {"request": request, "error": "Role not found"},
        )

    # Check if configuration exists
    existing_config = (
        db.query(WeightConfiguration)
        .filter(WeightConfiguration.role_id == role_id, WeightConfiguration.name == config_name)
        .first()
    )

    if existing_config:
        config = existing_config
        db.query(WeightItem).filter(WeightItem.configuration_id == config.id).delete()
    else:
        config = WeightConfiguration(
            role_id=role_id,
            name=config_name,
            total_allocated=total_allocated,
            scale_factor=100.0 / total_allocated if total_allocated > 0 else 1.0,
        )
        db.add(config)
        db.commit()
        db.refresh(config)

    # Build weight items for DB and JSON
    db_items = []
    json_items = []
    for req_id, weight in weight_map.items():
        req = db.query(Requirement).filter(Requirement.id == req_id).first()
        weight_item = WeightItem(
            configuration_id=config.id,
            requirement_id=req_id,
            weight_percentage=weight,
        )
        db.add(weight_item)
        db_items.append(weight_item)

        if req:
            json_items.append({
                "req_id": req.req_id,
                "name": req.name,
                "category": req.category,
                "requirement_type": req.requirement_type,
                "weight_percentage": weight,
                "expected_years": None,
                "notes": None,
            })

    db.commit()

    # Export to JSON file
    scale_factor = 100.0 / total_allocated if total_allocated > 0 else 1.0
    json_path = export_config_to_json(
        role_name=role.name,
        config_name=config_name,
        weight_items=json_items,
        total_allocated=total_allocated,
        scale_factor=scale_factor,
    )

    return _render(
        "partials/success.html",
        {
            "request": request,
            "message": f"Configuration '{config_name}' saved to DB and JSON!",
            "config_id": config.id,
            "role_name": role.name,
            "json_path": str(json_path),
        },
    )


@router.get("/api/htmx/configurations/{role_id}", response_class=HTMLResponse)
def htmx_configurations_list(
    request: Request,
    role_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """HTMX endpoint to list configurations for a role."""
    configurations = (
        db.query(WeightConfiguration)
        .filter(WeightConfiguration.role_id == role_id)
        .all()
    )

    # Build enriched config data with weight items + requirement names
    config_data = []
    for config in configurations:
        weight_items_raw = (
            db.query(WeightItem)
            .filter(WeightItem.configuration_id == config.id)
            .all()
        )
        items_for_template = []
        for wi in weight_items_raw:
            req = db.query(Requirement).filter(Requirement.id == wi.requirement_id).first()
            items_for_template.append({
                "requirement_id": wi.requirement_id,
                "requirement_req_id": req.req_id if req else f"REQ-{wi.requirement_id}",
                "requirement_name": req.name if req else "Unknown",
                "category": req.category if req else "Unknown",
                "weight_percentage": wi.weight_percentage,
            })
        config_data.append({
            "id": config.id,
            "name": config.name,
            "total_allocated": config.total_allocated,
            "created_at": config.created_at,
            "weight_items": items_for_template,
        })

    return _render(
        "partials/configurations_list.html",
        {"request": request, "configurations": config_data},
    )
