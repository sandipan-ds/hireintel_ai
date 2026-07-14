"""API routes for role and requirement management."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from recruiter.src.models.database import Requirement, Role, get_db
from recruiter.src.schemas.weight_config import (
    RequirementListResponse,
    RequirementResponse,
    RoleListResponse,
    RoleResponse,
)
from recruiter.src.services.subquery_parser import get_all_role_subqueries, get_role_subquery

router = APIRouter(prefix="/api/roles", tags=["roles"])


@router.get("/", response_model=RoleListResponse)
def list_roles(db: Session = Depends(get_db)) -> RoleListResponse:
    """List all available roles with their requirement counts."""
    roles = db.query(Role).all()

    role_responses = []
    for role in roles:
        requirements_count = db.query(Requirement).filter(Requirement.role_id == role.id).count()
        configurations_count = len(role.configurations) if role.configurations else 0

        role_responses.append(
            RoleResponse(
                id=role.id,
                name=role.name,
                display_name=role.display_name,
                description=role.description,
                jd_file_path=role.jd_file_path,
                subquery_file_path=role.subquery_file_path,
                created_at=role.created_at,
                updated_at=role.updated_at,
                requirements_count=requirements_count,
                configurations_count=configurations_count,
            )
        )

    return RoleListResponse(roles=role_responses, total=len(role_responses))


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(role_id: int, db: Session = Depends(get_db)) -> RoleResponse:
    """Get a specific role by ID."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    requirements_count = db.query(Requirement).filter(Requirement.role_id == role.id).count()
    configurations_count = len(role.configurations) if role.configurations else 0

    return RoleResponse(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        jd_file_path=role.jd_file_path,
        subquery_file_path=role.subquery_file_path,
        created_at=role.created_at,
        updated_at=role.updated_at,
        requirements_count=requirements_count,
        configurations_count=configurations_count,
    )


@router.get("/by-name/{role_name}", response_model=RoleResponse)
def get_role_by_name(role_name: str, db: Session = Depends(get_db)) -> RoleResponse:
    """Get a specific role by name."""
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    requirements_count = db.query(Requirement).filter(Requirement.role_id == role.id).count()
    configurations_count = len(role.configurations) if role.configurations else 0

    return RoleResponse(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        jd_file_path=role.jd_file_path,
        subquery_file_path=role.subquery_file_path,
        created_at=role.created_at,
        updated_at=role.updated_at,
        requirements_count=requirements_count,
        configurations_count=configurations_count,
    )


@router.get("/{role_id}/requirements", response_model=RequirementListResponse)
def get_role_requirements(
    role_id: int,
    category: str = None,
    db: Session = Depends(get_db),
) -> RequirementListResponse:
    """Get all requirements for a role, optionally filtered by category."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    query = db.query(Requirement).filter(Requirement.role_id == role_id)
    if category:
        query = query.filter(Requirement.category == category)

    requirements = query.all()

    # Group by category
    by_category: Dict[str, List[RequirementResponse]] = {}
    for req in requirements:
        req_response = RequirementResponse(
            id=req.id,
            role_id=req.role_id,
            req_id=req.req_id,
            name=req.name,
            category=req.category,
            requirement_type=req.requirement_type,
            description=req.description,
            subquery_count=req.subquery_count,
            scoring_formula=req.scoring_formula,
            created_at=req.created_at,
        )

        if req.category not in by_category:
            by_category[req.category] = []
        by_category[req.category].append(req_response)

    return RequirementListResponse(
        requirements=[RequirementResponse(
            id=req.id,
            role_id=req.role_id,
            req_id=req.req_id,
            name=req.name,
            category=req.category,
            requirement_type=req.requirement_type,
            description=req.description,
            subquery_count=req.subquery_count,
            scoring_formula=req.scoring_formula,
            created_at=req.created_at,
        ) for req in requirements],
        total=len(requirements),
        by_category=by_category,
    )


@router.post("/sync-from-subquery", response_model=Dict[str, Any])
def sync_roles_from_subquery(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Sync roles and requirements from SubQuery documents."""
    subquery_data = get_all_role_subqueries()

    synced_roles = 0
    synced_requirements = 0
    errors = []

    for role_name, data in subquery_data.items():
        try:
            # Check if role exists
            role = db.query(Role).filter(Role.name == role_name).first()

            if not role:
                # Create new role
                role = Role(
                    name=role_name,
                    display_name=role_name.replace("_", " ").replace("-", " ").title(),
                    description=f"Role for {role_name}",
                    subquery_file_path=data["file_path"],
                )
                db.add(role)
                db.commit()
                db.refresh(role)
                synced_roles += 1

            # Sync requirements
            for req_data in data["requirements"]:
                # Check if requirement exists
                existing_req = (
                    db.query(Requirement)
                    .filter(
                        Requirement.role_id == role.id,
                        Requirement.req_id == req_data["req_id"],
                    )
                    .first()
                )

                if not existing_req:
                    # Create new requirement
                    requirement = Requirement(
                        role_id=role.id,
                        req_id=req_data["req_id"],
                        name=req_data["name"],
                        category=req_data["category"],
                        requirement_type=req_data["requirement_type"],
                        description=req_data["description"],
                        subquery_count=req_data["subquery_count"],
                        scoring_formula=req_data["scoring_formula"],
                    )
                    db.add(requirement)
                    synced_requirements += 1

            db.commit()

        except Exception as e:
            errors.append(f"Error syncing {role_name}: {str(e)}")
            db.rollback()

    return {
        "synced_roles": synced_roles,
        "synced_requirements": synced_requirements,
        "total_roles": len(subquery_data),
        "total_requirements": sum(
            data["total_requirements"] for data in subquery_data.values()
        ),
        "errors": errors,
    }
