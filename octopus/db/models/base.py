"""
Base SQLAlchemy model configuration.

This module provides the base declarative model and metadata configuration
for all database models in the application. It sets up consistent naming
conventions and provides common model functionality.
"""

from typing import Any
from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base, declared_attr

# Define naming convention for constraints and indexes
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",  # Index
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # Unique constraint
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # Check constraint
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",  # Foreign key
    "pk": "pk_%(table_name)s"  # Primary key
}

# Configure metadata with naming convention
metadata = MetaData(naming_convention=NAMING_CONVENTION)

class BaseModel:
    """Base model class providing common functionality for all models."""
    
    @declared_attr
    def __tablename__(cls) -> str:
        """
        Generate table name automatically from class name.
        Converts CamelCase to snake_case (e.g., MyModel -> my_model).
        """
        return ''.join(
            ['_' + c.lower() if c.isupper() else c for c in cls.__name__]
        ).lstrip('_')
    
    def __repr__(self) -> str:
        """
        Provide a string representation of the model instance.
        Includes class name and primary key if available.
        """
        attrs = []
        for key in self.__mapper__.columns.keys():
            if key == 'id':  # Assuming 'id' is common primary key name
                attrs.append(f"id={getattr(self, key)}")
                break
        return f"<{self.__class__.__name__}({', '.join(attrs)})>"

# Create base with custom metaclass
Base = declarative_base(metadata=metadata, cls=BaseModel)
