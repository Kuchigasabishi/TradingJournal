import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Base
from app.db.session import make_engine, make_session_factory
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: unit tests must never pick up a developer's .env.
    return Settings(app_env="test", database_url="sqlite://", app_timezone="America/New_York", auto_migrate=False, _env_file=None)


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Session:
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def client(settings, engine) -> TestClient:
    return TestClient(create_app(settings, engine))
