"""Database configuration and models for scalable weight configuration system.

Uses SQLAlchemy with SQLite for development, can migrate to PostgreSQL for production.
Designed to handle 1000s of roles with multiple recruiters and configurations.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    relationship,
    sessionmaker,
)

# Database path
ROOT = Path(__file__).resolve().parent.parent.parent
DATABASE_PATH = ROOT / "data" / "hireintel.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Create engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Role(Base):
    """Job role model - stores all available roles."""
    __tablename__ = "roles"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    name: Mapped[str] = Column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = Column(String(255), nullable=False)
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    jd_file_path: Mapped[Optional[str]] = Column(String(500), nullable=True)
    subquery_file_path: Mapped[Optional[str]] = Column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    requirements = relationship("Requirement", back_populates="role", cascade="all, delete-orphan")
    configurations = relationship("WeightConfiguration", back_populates="role", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Role(id={self.id}, name='{self.name}')>"


class Requirement(Base):
    """Requirement model - stores all requirements for each role."""
    __tablename__ = "requirements"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    role_id: Mapped[int] = Column(Integer, ForeignKey("roles.id"), nullable=False)
    req_id: Mapped[str] = Column(String(50), nullable=False)  # e.g., "REQ-001"
    name: Mapped[str] = Column(String(500), nullable=False)
    category: Mapped[str] = Column(String(100), nullable=False)  # Core Skill, Preferred Skill, Experience, Education, Certification
    requirement_type: Mapped[str] = Column(String(50), nullable=False)  # required, preferred
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    subquery_count: Mapped[int] = Column(Integer, default=1)
    scoring_formula: Mapped[Optional[str]] = Column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    role = relationship("Role", back_populates="requirements")
    weight_items = relationship("WeightItem", back_populates="requirement", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Requirement(id={self.id}, req_id='{self.req_id}', name='{self.name}')>"


class Recruiter(Base):
    """Recruiter model - stores recruiter information."""
    __tablename__ = "recruiters"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    name: Mapped[str] = Column(String(255), nullable=False)
    email: Mapped[str] = Column(String(255), unique=True, index=True, nullable=False)
    company: Mapped[Optional[str]] = Column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), nullable=False
    )

    # Relationships
    configurations = relationship("WeightConfiguration", back_populates="recruiter", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Recruiter(id={self.id}, name='{self.name}')>"


class WeightConfiguration(Base):
    """Weight configuration model - stores weight configs for each role/recruiter."""
    __tablename__ = "weight_configurations"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    role_id: Mapped[int] = Column(Integer, ForeignKey("roles.id"), nullable=False)
    recruiter_id: Mapped[Optional[int]] = Column(Integer, ForeignKey("recruiters.id"), nullable=True)
    name: Mapped[str] = Column(String(255), nullable=False)  # e.g., "Default Config", "Senior Level"
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    total_allocated: Mapped[float] = Column(Float, default=0.0, nullable=False)
    scale_factor: Mapped[float] = Column(Float, default=1.0, nullable=False)
    is_active: Mapped[bool] = Column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    role = relationship("Role", back_populates="configurations")
    recruiter = relationship("Recruiter", back_populates="configurations")
    weight_items = relationship("WeightItem", back_populates="configuration", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<WeightConfiguration(id={self.id}, name='{self.name}')>"


class WeightItem(Base):
    """Weight item model - stores individual weight percentages."""
    __tablename__ = "weight_items"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    configuration_id: Mapped[int] = Column(Integer, ForeignKey("weight_configurations.id"), nullable=False)
    requirement_id: Mapped[int] = Column(Integer, ForeignKey("requirements.id"), nullable=False)
    weight_percentage: Mapped[float] = Column(Float, nullable=False)  # 0-100%
    expected_years: Mapped[Optional[float]] = Column(Float, nullable=True)  # Optional expected years
    notes: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    configuration = relationship("WeightConfiguration", back_populates="weight_items")
    requirement = relationship("Requirement", back_populates="weight_items")

    def __repr__(self) -> str:
        return f"<WeightItem(id={self.id}, weight={self.weight_percentage})>"


# Database initialization
def init_db() -> None:
    """Initialize the database and create all tables."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Get a database session (non-dependency version)."""
    return SessionLocal()
