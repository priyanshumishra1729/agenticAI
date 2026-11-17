from app.database import init_db
from app.db.seed_synthetic_data import seed_synthetic_data


def seed_demo_data():
    init_db()
    seed_synthetic_data()
