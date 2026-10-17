"""
Seed a few demo employees (one per lane) so you can test role-based login.
The CEO is always bootstrapped from .env — this only adds the rest.
Each demo password is generated randomly and displayed once.

    python run.py --seed
"""
import secrets

from engine.auth.users import users

DEMO = [
    ("coo@example.com", "Demo COO", "COO"),
    ("dev@example.com", "Demo Dev", "Software Engineer"),
    ("prompt@example.com", "Demo Prompt Eng", "Prompt Engineer"),
    ("marketer@example.com", "Demo Marketer", "Digital Marketing Manager"),
    ("bd@example.com", "Demo BD", "Business Development Manager"),
]


def main():
    for email, name, role in DEMO:
        if users.get(email):
            print(f"[seed] exists: {email}")
            continue
        try:
            pw = secrets.token_urlsafe(24)
            users.create(email, name, role, pw)
            print(f"[seed] created {email} ({role}) one-time password: {pw}")
        except Exception as e:  # noqa: BLE001
            print(f"[seed] skip {email}: {e}")
    print("[seed] done. CEO login is set in .env.")


if __name__ == "__main__":
    main()
