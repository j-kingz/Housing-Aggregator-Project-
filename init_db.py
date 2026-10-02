# Sets up the MySQL database for the project.
#
#   python init_db.py           create the database + tables if they don't exist
#   python init_db.py --reset   drop everything and start again (asks first)

import sys

import pymysql

from config import Config
from app import create_app
from app.extensions import db
from app.models import Role

ROLES = [
    ("Renter", "Searches for housing and views price analytics"),
    ("Landlord", "Adds and manages their own property listings"),
    ("Administrator", "Manages user accounts and scraping sources"),
]


def make_database(reset=False):
    conn = pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
    )
    with conn.cursor() as cur:
        if reset:
            cur.execute(f"DROP DATABASE IF EXISTS `{Config.DB_NAME}`")
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{Config.DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.close()


def add_roles():
    for name, description in ROLES:
        if not Role.query.filter_by(name=name).first():
            db.session.add(Role(name=name, description=description))
    db.session.commit()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    if reset:
        answer = input(f"This deletes ALL data in '{Config.DB_NAME}'. Type yes to continue: ")
        if answer.strip().lower() != "yes":
            print("Cancelled.")
            sys.exit()

    make_database(reset)

    app = create_app()
    with app.app_context():
        db.create_all()
        add_roles()

    print(f"'{Config.DB_NAME}' is ready.")
