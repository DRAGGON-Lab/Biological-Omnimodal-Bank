# Administration

## Roles

A workspace has three roles:

- Owner: manages members and settings, publishes or withdraws studies, and can edit all data.
- Editor: creates and edits investigations, studies, samples, assays, mappings, and analyses.
- Viewer: reads all workspace data but cannot change it.

At least one owner must remain in every workspace. Removing a member revokes that workspace's access but does not delete their account or scientific records attributed to them.

## First PI

Use the one-time `bootstrap-owner` command described in [Install and deploy](install-and-deploy.md). It refuses to run after any account exists.

## Adding students

On a closed-signup production server, create a managed student account first:

```sh
docker compose --env-file .env -f compose.production.yml exec bob \
  python -m bob.admin create-user \
  --email student@example.edu --name "Student Name"
```

The command reads and confirms a temporary password interactively and deliberately does not create a personal workspace. The PI can then invite that email from Workspace settings as a viewer or editor. The student signs in, changes the temporary password under Account settings, and accepts the invitation.

This is the safe local-account bridge for BOB 1.0. Expiring, tokenized email invitations and forced first-login password changes remain required follow-up work before broad or self-service onboarding.

Do not assign the owner role merely to let a student edit data. Owners can publish, withdraw, delete private workspace content, and manage other members.

## Publication

Publishing makes a study readable by every signed-in account on the server. Each subsequent saved change creates a new immutable version. A published study can be withdrawn but cannot be erased through the normal UI, so cited links retain a withdrawal notice.

## Operational checks

- `/livez`: the process is responding.
- `/readyz`: database, migrations, and artifact storage are usable.
- `/health`: compatibility endpoint containing version and mode.
- `docker compose ... logs bob`: application failures.
- `docker compose ... logs migrate`: schema-upgrade failures.

Never send `app_secret`, database credentials, session cookies, API tokens, raw confidential data, or SynBioHub tokens in a support report.
