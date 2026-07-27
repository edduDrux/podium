"""Modelos SQLAlchemy. Importados aqui para o autogenerate do Alembic enxergá-los."""

from app.models.base import Base
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.models.user import User

__all__ = ["Base", "Feedback", "Presentation", "User"]
