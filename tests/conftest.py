import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://corp:corp@localhost:5432/corp_test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://corp:corp@localhost:5432/corp_test")
