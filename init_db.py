"""
Run this once to create the MySQL database (if missing) and all tables.
Usage (from the project folder, with the virtual environment active):
    python init_db.py
"""
import pymysql
from config import Config
from app import create_app
from app.extensions import db

# Step 1: make sure the database itself exists before Flask connects to it
connection = pymysql.connect(
    host=Config.DB_HOST,
    port=int(Config.DB_PORT),
    user=Config.DB_USER,
    password=Config.DB_PASSWORD,
)
with connection.cursor() as cursor:
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS {Config.DB_NAME} "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
connection.close()

# Step 2: create every table defined in app/models.py
app = create_app()
with app.app_context():
    db.create_all()
    print(f"Database '{Config.DB_NAME}' and all tables are ready.")
