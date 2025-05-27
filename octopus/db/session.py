import os
import logging
from typing import Generator, ContextManager
from contextlib import contextmanager

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Required database configuration
REQUIRED_ENV_VARS = ['PGUSER', 'PGPASSWORD', 'PGHOST', 'PGDATABASE']

def create_database_url() -> URL:
    """
    Create database URL from environment variables.
    
    Returns:
        URL: SQLAlchemy URL object for database connection
        
    Raises:
        ValueError: If required environment variables are missing
        TypeError: If port is not a valid integer
    """
    # Check for required environment variables
    missing_vars = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Parse port number
    try:
        port = int(os.getenv('PGPORT', '5432'))
    except ValueError as e:
        raise TypeError(f"Invalid port number: {str(e)}")
    
    return URL.create(
        drivername="postgresql+psycopg2",
        username=os.environ['PGUSER'],
        password=os.environ['PGPASSWORD'],
        host=os.environ['PGHOST'],
        port=port,
        database=os.environ['PGDATABASE'],
    )

try:
    DATABASE_URL = create_database_url()
    # Configure SQLAlchemy logging more selectively
    engine = create_engine(
        DATABASE_URL,
        echo=False,  # Disable full SQL logging
        echo_pool=False,  # Disable connection pool logging
        logging_name='sqlalchemy.engine'
    )
    SessionLocal = sessionmaker(
        bind=engine,
        expire_on_commit=False
    )
except (ValueError, TypeError) as e:
    logger.error(f"Failed to configure database: {str(e)}")
    raise
except SQLAlchemyError as e:
    logger.error(f"Failed to create database engine: {str(e)}")
    raise

@contextmanager
def get_session() -> ContextManager[Session]:
    """
    Get a database session.
    
    Yields:
        Session: Database session
        
    Raises:
        SQLAlchemyError: If there's an error creating the session
    """
    session = SessionLocal()
    try:
        yield session
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database session error: {str(e)}")
        raise
    finally:
        session.close()
