"""One-time local setup for WORKCODE with PostgreSQL.

    python setup_local.py

It asks for your PostgreSQL details, then:
  1. checks that it can connect,
  2. creates the database if it does not exist (an existing database is never dropped),
  3. writes backend/.env with new random secrets (an existing .env is kept unless you agree to replace it),
  4. creates or updates the tables (alembic upgrade head),
  5. creates the demo accounts or your own first admin.

Run it again any time: every step is safe to repeat.
"""
import getpass
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"


def ask(question, default=""):
    """Ask in the terminal. With WORKCODE_SETUP_AUTO=1 the default is used without asking (for scripted runs)."""
    if os.environ.get("WORKCODE_SETUP_AUTO") == "1":
        return default
    answer = input(f"{question} [{default}]: ").strip()
    return answer or default


def stop(message):
    print("\nSTOPPED: " + message)
    sys.exit(1)


def run(args, extra_env=None):
    """Run a command in the backend folder and stop if it fails."""
    env = dict(os.environ, **(extra_env or {}))
    result = subprocess.run([sys.executable, *args], cwd=HERE, env=env)
    if result.returncode != 0:
        stop("command failed: python " + " ".join(args))


def read_env_file():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def main():
    try:
        import psycopg2
    except ImportError:
        stop("Python packages are missing. Run first:  python -m pip install -r requirements.txt")

    print("WORKCODE local setup (PostgreSQL)\n")
    host = ask("PostgreSQL host", os.environ.get("PGHOST", "127.0.0.1"))
    port = ask("PostgreSQL port", os.environ.get("PGPORT", "5433"))
    user = ask("PostgreSQL user", os.environ.get("PGUSER", "postgres"))
    password = os.environ.get("PGPASSWORD") or getpass.getpass(f"Password of PostgreSQL user '{user}': ")
    database = ask("Database name for WORKCODE", os.environ.get("PGDATABASE", "workcode_v2"))
    if not database.replace("_", "").isalnum():
        stop("Use only letters, numbers and _ in the database name.")

    # 1. connect to the server
    try:
        server = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres", connect_timeout=8)
    except Exception as error:
        stop(f"Cannot connect to PostgreSQL on {host}:{port} as '{user}'.\n  {str(error).strip()}\n"
             "  Check that PostgreSQL is running, and that the port and password are right.")
    server.autocommit = True
    cursor = server.cursor()
    cursor.execute("select version()")
    print("\n1. Connected:", cursor.fetchone()[0].split(",")[0])

    # 2. create the database when it is missing
    cursor.execute("select 1 from pg_database where datname = %s", (database,))
    if cursor.fetchone():
        print(f"2. Database '{database}' already exists, it is kept as it is.")
    else:
        cursor.execute(f'create database "{database}" encoding \'UTF8\'')
        print(f"2. Database '{database}' created.")
    server.close()

    # 3. write .env
    url = f"postgresql+psycopg2://{quote(user, safe="")}:{quote(password, safe="")}@{host}:{port}/{database}"
    old = read_env_file()
    write = True
    if ENV_FILE.exists():
        same_database = old.get("DATABASE_URL") == url
        if same_database:
            write = False
            print("3. backend/.env already points to this database, it is kept (secrets unchanged).")
        else:
            # Docker mode (no questions): the database chosen in the compose files wins; the secrets are kept below.
            auto = os.environ.get("WORKCODE_SETUP_AUTO") == "1"
            answer = ask("backend/.env exists and points to another database. Replace it? (y/n)", "y" if auto else "n").lower()
            if answer != "y":
                stop("backend/.env was not changed. Rename or delete it and run this script again.")
            ENV_FILE.replace(HERE / ".env.backup")
            print("   Old file saved as backend/.env.backup")
    if write:
        example = (HERE / ".env.example").read_text(encoding="utf-8").splitlines()
        new_values = {
            "DATABASE_URL": url,
            # Keep the old secrets when there are any: changing them signs everyone out and makes stored AI keys unreadable.
            "JWT_SECRET": old.get("JWT_SECRET") if len(old.get("JWT_SECRET", "")) >= 32 else secrets.token_urlsafe(48),
            "AI_KEY_SECRET": old.get("AI_KEY_SECRET") or secrets.token_urlsafe(48),
        }
        # mail settings typed in by hand survive a change of database
        for key, value in old.items():
            if key.startswith(("SMTP_", "GMAIL_", "MAIL_")) or key == "APP_URL":
                new_values[key] = value
        lines = []
        for line in example:
            key = line.split("=", 1)[0].strip()
            lines.append(f"{key}={new_values[key]}" if key in new_values and not line.startswith("#") else line)
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        kept = len(old.get("JWT_SECRET", "")) >= 32
        print("3. backend/.env written (" + ("JWT_SECRET and AI_KEY_SECRET kept from the old file)." if kept else "new random JWT_SECRET and AI_KEY_SECRET)."))

    # 4. tables
    print("4. Creating / updating the tables ...")
    run(["-m", "alembic", "upgrade", "head"])

    # 5. first accounts
    check = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=database)
    cursor = check.cursor()
    cursor.execute("select count(*) from users")
    people = cursor.fetchone()[0]
    cursor.execute("select count(*) from information_schema.tables where table_schema = 'public'")
    tables = cursor.fetchone()[0]
    check.close()
    print(f"   {tables} tables in '{database}'.")
    if people:
        print(f"5. The database already has {people} user(s), no account was created.")
    else:
        choice = ask("5. Create (d) demo accounts for all roles, (a) only your own admin, or (n) nothing?", "d").lower()
        if choice == "d":
            run(["-m", "app.demo_seed"])
        elif choice == "a":
            email = ask("   Admin e-mail", "admin@company.com")
            name = ask("   Admin full name", "Admin")
            run(["-m", "app.seed", email, name])

    print("\nDone. Start the two parts in two terminals:")
    print("  backend :  python -m uvicorn app.main:app --port 8000     (in the backend folder)")
    print("  frontend:  npm install   then   npm run dev         (in the frontend folder)")
    print("Then open http://localhost:5173")


if __name__ == "__main__":
    main()
