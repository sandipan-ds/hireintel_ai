"""Initialize database with roles and requirements from SubQuery documents."""

from __future__ import annotations

import sys
from pathlib import Path

# Add root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.models.database import Requirement, Role, get_db_session, init_db
from src.services.subquery_parser import get_all_role_subqueries


def initialize_database() -> None:
    """Initialize database with roles and requirements."""
    print("Initializing database...")
    init_db()

    print("Syncing roles from SubQuery documents...")
    subquery_data = get_all_role_subqueries()

    db = get_db_session()
    try:
        synced_roles = 0
        synced_requirements = 0

        for role_name, data in subquery_data.items():
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
                print(f"  Created role: {role_name}")

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

        print(f"\nSync complete:")
        print(f"  Roles created: {synced_roles}")
        print(f"  Requirements created: {synced_requirements}")
        print(f"  Total roles: {len(subquery_data)}")
        print(
            f"  Total requirements: {sum(data['total_requirements'] for data in subquery_data.values())}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    initialize_database()
