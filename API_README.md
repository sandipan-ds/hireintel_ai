# HireIntel AI - Weight Configuration API

A FastAPI + HTMX application for configuring recruiter weights for candidate evaluation.

## Features

- **Dual storage**: SQLite database + JSON files (scoring-engine compatible)
- **Role-based weight configuration**: Configure weights for each requirement per role
- **Real-time validation**: Weights must sum to 100% with instant feedback
- **Category breakdown**: See weights by category (Skills, Education, Certifications, etc.)
- **Scalable design**: Database-backed for 1000s of roles
- **HTMX-powered UI**: No JavaScript framework required

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements_api.txt
```

### 2. Initialize Database

```bash
python scripts/init_database.py
```

### 3. Start Server

```bash
python -m uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

### 4. Open Browser

Navigate to http://localhost:8000/configure

## Dual Storage (DB + JSON)

Every save writes to **both** SQLite and JSON file:

| Storage | Location | Purpose |
|---------|----------|---------|
| SQLite | `data/hireintel.db` | API queries, configs, audit trail |
| JSON | `data/job_descriptions/{role}/{role}_WeightConfig_{name}.json` | Scoring engine input |

**JSON format** matches the existing `*_RecruiterWeights_EXAMPLE.json` format used by `unified_scorer.py`.

**On delete**: Both DB record and JSON file are removed.

## Architecture

```
src/
├── api/
│   ├── app.py              # FastAPI application
│   ├── roles.py            # Role API endpoints
│   ├── weights.py          # Weight configuration API endpoints
│   └── pages.py            # HTML page routes (HTMX)
├── models/
│   └── database.py         # SQLAlchemy models
├── schemas/
│   └── weight_config.py    # Pydantic schemas
├── services/
│   ├── subquery_parser.py  # SubQuery document parser
│   └── json_export.py      # JSON file export/import
└── templates/
    ├── base.html           # Base template
    ├── home.html           # Home page
    ├── configure.html      # Configuration page
    └── partials/           # HTMX partial templates
```

## API Endpoints

### Roles

- `GET /api/roles/` - List all roles
- `GET /api/roles/{id}` - Get role details
- `GET /api/roles/{id}/requirements` - Get role requirements
- `POST /api/roles/sync-from-subquery` - Sync roles from SubQuery documents

### Weight Configurations

- `GET /api/weights/configurations` - List configurations
- `GET /api/weights/configurations/{id}` - Get configuration
- `POST /api/weights/configurations` - Create configuration
- `PUT /api/weights/configurations/{id}` - Update configuration
- `DELETE /api/weights/configurations/{id}` - Delete configuration
- `POST /api/weights/validate` - Validate configuration

### HTMX Endpoints

- `GET /api/htmx/roles` - Roles list as HTML
- `GET /api/htmx/requirements/{role_id}` - Requirements form as HTML
- `GET /api/htmx/validate/{role_id}` - Validation summary as HTML
- `POST /api/htmx/save/{role_id}` - Save configuration (DB + JSON)
- `GET /api/htmx/configurations/{role_id}` - Configurations list as HTML

### JSON Export/Import

- `export_config_to_json()` - Save config to JSON file
- `load_config_from_json()` - Load config from JSON file
- `list_json_configs()` - List all JSON configs for a role
- `delete_json_config()` - Delete a JSON config file

## Database Schema

### Roles
- `id`: Primary key
- `name`: Role name (unique)
- `display_name`: Display name
- `description`: Role description
- `jd_file_path`: Path to job description
- `subquery_file_path`: Path to SubQuery document

### Requirements
- `id`: Primary key
- `role_id`: Foreign key to roles
- `req_id`: Requirement ID (e.g., REQ-001)
- `name`: Requirement name
- `category`: Category (Core Skill, Education, etc.)
- `requirement_type`: Required or preferred
- `description`: Requirement description
- `subquery_count`: Number of sub-queries
- `scoring_formula`: Scoring formula

### Weight Configurations
- `id`: Primary key
- `role_id`: Foreign key to roles
- `recruiter_id`: Foreign key to recruiters (optional)
- `name`: Configuration name
- `description`: Configuration description
- `total_allocated`: Total allocated percentage
- `scale_factor`: Scale factor for normalization
- `is_active`: Whether configuration is active

### Weight Items
- `id`: Primary key
- `configuration_id`: Foreign key to configurations
- `requirement_id`: Foreign key to requirements
- `weight_percentage`: Weight percentage (0-100)
- `expected_years`: Expected years of experience (optional)
- `notes`: Additional notes

## Weight Configuration Format

### SQLite Storage

```sql
-- weight_configurations table
INSERT INTO weight_configurations (role_id, name, total_allocated, scale_factor)
VALUES (1, 'Senior Level', 100.0, 1.0);

-- weight_items table
INSERT INTO weight_items (configuration_id, requirement_id, weight_percentage)
VALUES (1, 1, 25.0);
```

### JSON Storage

```json
{
  "role": "BusinessAnalyst",
  "config_name": "Senior Level",
  "created_by": "Recruiter",
  "created_date": "2026-07-01",
  "scale_factor": 1.0,
  "requirements_weights": [
    {
      "requirement_id": "REQ-001",
      "requirement_name": "Business Analysis & Requirement Gathering",
      "category": "Core Skill",
      "type": "required",
      "weight_percentage": 25.0
    }
  ],
  "summary": {
    "total_allocated": 100.0,
    "by_category": { ... }
  }
}
```

## Validation Rules

1. **Total must equal 100%**: Sum of all weights must be exactly 100%
2. **No negative weights**: All weights must be >= 0
3. **No weights over 100%**: Individual weights must be <= 100
4. **All requirements rated**: Each requirement should have a weight

## Scalability Features

1. **Database-backed**: SQLite for development, PostgreSQL for production
2. **Normalized weights**: Scale factor for consistent scoring
3. **Multiple configurations**: Support for different recruiter preferences
4. **Category-based organization**: Group related requirements
5. **Audit trail**: Track creation and update timestamps

## Development

### Adding New Roles

1. Add SubQuery document to `data/job_descriptions/{role_name}/{role_name}_SubQuery.md`
2. Run sync: `POST /api/roles/sync-from-subquery`
3. Or manually: `python scripts/init_database.py`

### Testing

```bash
# Run test script
python scripts/test_weight_api.py

# Run API tests
pytest tests/
```

### Database Migration

For production, migrate to PostgreSQL:

1. Install PostgreSQL driver: `pip install psycopg2-binary`
2. Update `DATABASE_URL` in `src/models/database.py`
3. Run migrations: `alembic upgrade head`
