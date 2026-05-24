"""Send alert digest emails via Resend."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"

_TIER_EMOJI = {
    "PHANTOM_FARE": "🔴",
    "FLASH_DEAL": "🟠",
    "DEAL": "🟢",
}
_TIER_LABEL = {
    "PHANTOM_FARE": "Phantom Fare (Members only)",
    "FLASH_DEAL": "Flash Deal",
    "DEAL": "Deal",
}


def send_alert_digest(
    session: Session,
    resend_api_key: str,
    to_email: str,
    from_email: str = "onboarding@resend.dev",
    since: datetime | None = None,
) -> int:
    """Send a digest email for new READY alerts. Returns count of alerts sent.

    Returns 0 without sending if there are no alerts in the window.
    """
    since = since or datetime.now(UTC) - timedelta(hours=25)
    alerts = _load_ready_alerts(session, since)
    if not alerts:
        logger.info("No READY alerts since %s — skipping email.", since.isoformat())
        return 0

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    subject = f"✈ {len(alerts)} flight deal(s) detected — {date_str}"
    text_body = _build_text_body(alerts, date_str)
    html_body = _build_html_body(alerts, date_str)

    response = httpx.post(
        _RESEND_URL,
        headers={"Authorization": f"Bearer {resend_api_key}"},
        json={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": text_body,
            "html": html_body,
        },
        timeout=15,
    )
    response.raise_for_status()
    logger.info("Sent alert digest: %d alert(s) to %s.", len(alerts), to_email)
    return len(alerts)


def _load_ready_alerts(session: Session, since: datetime) -> list[dict[str, Any]]:
    result = session.execute(
        text(
            """
            SELECT
                tier, origin, destination, airline_code, cabin,
                fare_native, native_currency, fare_display, display_currency,
                baseline_price, percent_saving, absolute_saving,
                urgency_flag, visibility
            FROM alerts
            WHERE status = 'READY'
              AND created_at >= :since
            ORDER BY
                CASE tier
                    WHEN 'PHANTOM_FARE' THEN 1
                    WHEN 'FLASH_DEAL'   THEN 2
                    ELSE 3
                END,
                percent_saving DESC
            """
        ),
        {"since": since},
    )
    return [dict(row._mapping) for row in result]


def _build_text_body(alerts: list[dict[str, Any]], date_str: str) -> str:
    lines = [
        f"Flight Deal Intelligence — {date_str}",
        f"{len(alerts)} new deal(s) detected",
        "=" * 48,
        "",
    ]
    for a in alerts:
        emoji = _TIER_EMOJI.get(str(a["tier"]), "")
        label = _TIER_LABEL.get(str(a["tier"]), str(a["tier"]))
        saving = _fmt_pct(a["percent_saving"])
        fare = _fmt_money(a["fare_native"], a["native_currency"])
        baseline = _fmt_money(a["baseline_price"], a["native_currency"])
        lines += [
            f"{emoji} {label}",
            f"   Route:    {a['origin']} → {a['destination']}  |  {a['airline_code']}  |  {a['cabin']}",
            f"   Fare:     {fare}  (baseline {baseline})",
            f"   Saving:   {saving}% off",
            "",
        ]
    lines += [
        "─" * 48,
        "Flight Deal Intelligence Wave 1",
        "Unsubscribe: remove ALERT_EMAIL_TO from GitHub secrets.",
    ]
    return "\n".join(lines)


def _build_html_body(alerts: list[dict[str, Any]], date_str: str) -> str:
    rows_html = ""
    for a in alerts:
        emoji = _TIER_EMOJI.get(str(a["tier"]), "")
        label = _TIER_LABEL.get(str(a["tier"]), str(a["tier"]))
        saving = _fmt_pct(a["percent_saving"])
        fare = _fmt_money(a["fare_native"], a["native_currency"])
        baseline = _fmt_money(a["baseline_price"], a["native_currency"])
        bg = {"PHANTOM_FARE": "#fff0f0", "FLASH_DEAL": "#fff7ed", "DEAL": "#f0fff4"}.get(
            str(a["tier"]), "#ffffff"
        )
        rows_html += f"""
        <tr style="background:{bg}">
          <td style="padding:10px 12px;font-weight:bold">{emoji} {label}</td>
          <td style="padding:10px 12px">{a['origin']} → {a['destination']}</td>
          <td style="padding:10px 12px">{a['airline_code']}</td>
          <td style="padding:10px 12px">{a['cabin'].title()}</td>
          <td style="padding:10px 12px;font-weight:bold">{fare}</td>
          <td style="padding:10px 12px;color:#6b7280">baseline {baseline}</td>
          <td style="padding:10px 12px;color:#16a34a;font-weight:bold">−{saving}%</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;color:#111;max-width:800px;margin:0 auto;padding:24px">
  <h2 style="margin:0 0 4px">✈ Flight Deal Intelligence</h2>
  <p style="color:#6b7280;margin:0 0 24px">{date_str} — {len(alerts)} new deal(s)</p>
  <table style="width:100%;border-collapse:collapse;font-size:14px">
    <thead>
      <tr style="background:#f3f4f6;text-align:left">
        <th style="padding:10px 12px">Tier</th>
        <th style="padding:10px 12px">Route</th>
        <th style="padding:10px 12px">Airline</th>
        <th style="padding:10px 12px">Cabin</th>
        <th style="padding:10px 12px">Fare</th>
        <th style="padding:10px 12px">Baseline</th>
        <th style="padding:10px 12px">Saving</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
  <p style="color:#9ca3af;font-size:12px;margin-top:32px">
    Flight Deal Intelligence Wave 1 · automated daily run
  </p>
</body>
</html>"""


def _fmt_money(amount: Any, currency: str) -> str:
    try:
        val = Decimal(str(amount))
        if val == val.to_integral():
            return f"{currency} {int(val):,}"
        return f"{currency} {val:,.2f}"
    except Exception:
        return f"{currency} {amount}"


def _fmt_pct(value: Any) -> str:
    try:
        val = Decimal(str(value))
        return str(int(val)) if val == val.to_integral() else f"{val:.1f}"
    except Exception:
        return str(value)
