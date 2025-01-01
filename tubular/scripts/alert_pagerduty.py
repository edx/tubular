"""
Command-line script to submit an alert to PagerDuty API.
"""

import logging
import sys
import traceback
import requests
import click

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
LOG = logging.getLogger(__name__)

@click.command("alert_pagerduty")
@click.option(
    '--routing_key',
    required=True,
    help="Routing key for PagerDuty Events API (Integration key).",
)
@click.option(
    '--message',
    required=True,
    help="Summary or title of the PagerDuty alert.",
)
@click.option(
    '--description',
    required=True,
    help="Details or description of the PagerDuty alert.",
)
@click.option(
    '--severity',
    default="error",
    type=click.Choice(['critical', 'error', 'warning', 'info'], case_sensitive=False),
    help="Severity of the alert (default: error).",
)
@click.option(
    '--source',
    default="custom-script",
    help="Source of the alert (default: custom-script).",
)
def alert_pagerduty(routing_key, message, description, severity, source):
    """
    Create a PagerDuty alert using the Events API.

    Arguments:
        routing_key: Integration key for PagerDuty.
        message: The alert summary or title.
        description: The alert details.
        severity: The severity level of the alert.
        source: The source of the alert.
    """
    try:
        logging.info("Creating alert on PagerDuty")
        
        # Define the payload for the PagerDuty Events API
        payload = {
            "routing_key": routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": message,
                "severity": severity,
                "source": source,
                "custom_details": {
                    "description": description
                }
            }
        }
        
        # Send the request to PagerDuty
        response = requests.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload
        )
        
        # Check the response status
        if response.status_code == 202:
            LOG.info("Alert successfully created on PagerDuty.")
        else:
            LOG.error("Failed to create alert. Response: %s", response.text)
            response.raise_for_status()
    except Exception as err:  # pylint: disable=broad-except
        traceback.print_exc()
        click.secho(f"Error: {err}", fg='red')
        sys.exit(1)


if __name__ == "__main__":
    alert_pagerduty()
