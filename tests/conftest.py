import os
os.environ["DATABASE_URL"]="sqlite:///./data/test.db"
os.environ["ENVIRONMENT"]="test"
from backend.database import Base,engine,SessionLocal
import pytest
@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
@pytest.fixture
def db():
    with SessionLocal() as session: yield session

