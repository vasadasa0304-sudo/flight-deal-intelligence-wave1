import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set. Check your .env file.")
    return create_engine(url, echo=False)

engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

if __name__ == "__main__":
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar()
        print("Connection successful.")
        print(version)
