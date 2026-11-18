# Corporate Convenience

Internal employee concerns and ticket management platform.

## Features
- Admin-created accounts; no public registration.
- Employee, support and administrator roles.
- Department queues for HR, IT, Finance and Operations.
- Explainable baseline classification suggestions.
- Human priority and department review with recorded reasons.
- Ticket history, audit records and resolved-ticket archive.
- SMTP notification integration.

## Local setup

Activate the virtual environment:

    source .venv/bin/activate

Install dependencies:

    pip install -r requirements.txt

Create the first administrator:

    flask --app app create-admin

Run the application:

    flask --app app run --debug

Open http://127.0.0.1:5000

Configure secrets and email settings in .env.
Never commit .env or the instance database.

The initial classifier is a transparent baseline, not a trained machine-learning model.
Email delivery requires valid SMTP credentials.
