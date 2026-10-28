# Makes an administrator account. Admins can't sign up through the website,
# so run this once from the project folder:
#
#   python create_admin.py

import re
import sys
from getpass import getpass

from app import create_app
from app.extensions import db
from app.models import Role, User

app = create_app()

with app.app_context():
    role = Role.query.filter_by(name="Administrator").first()
    if role is None:
        sys.exit("No Administrator role found. Run python init_db.py first.")

    print("Create an admin account\n")
    firstname = input("First name: ").strip()
    lastname = input("Last name: ").strip()
    email = input("Email: ").strip().lower()

    if not (firstname and lastname and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email)):
        sys.exit("Name and a valid email are required.")

    existing = User.query.filter_by(email=email).first()
    if existing:
        answer = input(f"{email} already has an account. Make it an admin? (y/n): ")
        if answer.strip().lower() != "y":
            sys.exit("Nothing changed.")
        existing.role = role
        existing.status = "active"
        db.session.commit()
        print(f"{email} is now an admin.")
        sys.exit()

    # getpass hides what you type
    password = getpass("Password (min 8 characters): ")
    if len(password) < 8:
        sys.exit("Password is too short.")
    if password != getpass("Confirm password: "):
        sys.exit("Passwords don't match.")

    admin = User(firstname=firstname, lastname=lastname, email=email, role=role)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    print(f"\nAdmin account created for {email}. Log in on the website to see the Admin tab.")
