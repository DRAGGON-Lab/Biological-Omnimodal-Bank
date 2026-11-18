# Install and deploy

## Local evaluation

Install Docker Desktop, then run:

```sh
docker compose up --build
```

This development stack binds only to `127.0.0.1`, uses SQLite, permits sign-up, and creates the documented demo account. It is not a production configuration.

## Single-lab production deployment

The reference production stack uses PostgreSQL, HTTPS through Caddy, closed sign-up, secure cookies, explicit migrations, an unprivileged application container, and file-backed secrets.

Prerequisites:

- A Linux server with Docker Engine and Compose v2.
- A DNS record for the BOB host pointing to the server.
- Inbound TCP ports 80 and 443.
- SMTP is not yet included in the 1.0 account flow; administrators create managed accounts with `python -m bob.admin create-user`, then owners invite them through the application.

Create the configuration:

```sh
cp .env.production.example .env
mkdir -p secrets
openssl rand -hex 48 > secrets/app_secret
openssl rand -base64 32 > secrets/db_password
chmod 600 secrets/app_secret secrets/db_password
```

Set `BOB_DOMAIN` in `.env`, then start the stack:

```sh
docker compose --env-file .env -f compose.production.yml up -d --build
```

The migration service must finish successfully before the web service starts. Check status with:

```sh
docker compose --env-file .env -f compose.production.yml ps
docker compose --env-file .env -f compose.production.yml logs migrate
```

Create the first PI account interactively:

```sh
docker compose --env-file .env -f compose.production.yml exec bob \
  python -m bob.admin bootstrap-owner \
  --email pi@example.edu --name "Principal Investigator" --workspace "Example Lab"
```

The bootstrap command runs only while the user table is empty and never accepts a password in arguments or environment variables.

## Production safety checks

`BOB_ENV=production` refuses to start when any of these conditions hold:

- Demo seeding or public sign-up is enabled.
- Secure cookies are disabled.
- The public base address is not HTTPS.
- SQLite is selected.
- trusted hosts are implicit.
- the application secret is absent.
- a CORS origin uses plain HTTP.

Use `/livez` for process liveness and `/readyz` for database, migration, and artifact-storage readiness.

## Upgrade

1. Back up PostgreSQL, the `bob-data` volume, and `secrets/app_secret` together.
2. Pull or check out the target release and review its migration notes.
3. Set `BOB_VERSION` in `.env`.
4. Run `docker compose --env-file .env -f compose.production.yml up -d --build`.
5. Confirm the migration service completed and `/readyz` reports `ready`.

Do not start an older application against a database after a non-reversible migration. Restore the pre-upgrade database and artifact backup instead.

## Data that must be backed up

- PostgreSQL database volume `bob-db`.
- Raw artifact volume `bob-data`.
- `secrets/app_secret`; losing it invalidates sessions and makes stored SynBioHub tokens unreadable.
- Deployment `.env` and secret-management instructions, stored outside the backup archive where appropriate.

Automated coordinated backup and restore verification remain tracked production work; until delivered, administrators must use an infrastructure snapshot or stop BOB briefly while capturing the database and artifact volume.
