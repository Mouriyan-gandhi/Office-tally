"""Local owner administration. Passwords are prompted, never passed as arguments."""
import argparse
import getpass
import secrets
from app import store
from app.server import password_hash


def main():
    parser = argparse.ArgumentParser(description='Add a user to the single-company office app')
    parser.add_argument('--role', choices=['owner','operator','viewer'], default='operator')
    args = parser.parse_args()
    from app.cloud import enabled
    if enabled():
        raise SystemExit('Cloud deployment is restricted to one verified Supabase admin; local user creation is disabled.')
    store.init()
    email = input('New user email: ').strip().lower()
    if '@' not in email:
        raise SystemExit('Enter a valid email address')
    password = getpass.getpass('Choose a password (12+ characters): ')
    if len(password) < 12 or password != getpass.getpass('Repeat password: '):
        raise SystemExit('Password is too short or does not match')
    with store.transaction() as db:
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (secrets.token_hex(16), email, password_hash(password), args.role))
        store.audit(db, 'local-admin', 'user_created', email)
    print('Account created. Only owners can approve posting.')

if __name__ == '__main__':
    main()
