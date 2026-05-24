"""Send a digest email for any READY alerts from the last 25 hours."""

from __future__ import annotations

import os
import sys

from sqlalchemy.orm import Session

from src.config import load_settings
from src.db_helpers import get_engine
from src.logging_config import configure_logging
from src.reporting.email_delivery import send_alert_digest


def main() -> int:
    settings = load_settings()
    configure_logging(settings.log_level)

    resend_api_key = os.environ.get("RESEND_API_KEY", "")
    to_email = os.environ.get("ALERT_EMAIL_TO", "")
    from_email = os.environ.get("ALERT_EMAIL_FROM", "onboarding@resend.dev")

    if not resend_api_key:
        print("RESEND_API_KEY not set — skipping email delivery.")
        return 0
    if not to_email:
        print("ALERT_EMAIL_TO not set — skipping email delivery.")
        return 0

    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            count = send_alert_digest(
                session,
                resend_api_key=resend_api_key,
                to_email=to_email,
                from_email=from_email,
            )
        if count:
            print(f"Email sent: {count} alert(s) delivered to {to_email}.")
        else:
            print("No new alerts — email not sent.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
