import logging
import sys
import traceback
import requests
import click

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

@click.command("close_pagerduty_alert")
@click.option(
    '--routing_key',
    required=True,
    help="Routing key for PagerDuty Events API v2.",
)
@click.option(
    '--dedup_key',
    required=True,
    help="Deduplication key of the PagerDuty alert to close.",
)
@click.option(
    '--source',
    default=None,
    help="Source of the request (optional)."
)
def close_pagerduty_alert(routing_key, dedup_key, source):
    """
    Close a PagerDuty alert

    Arguments:
        routing_key: Events API v2 routing key
        dedup_key: The deduplication key of the alert
        source: The source of the request (optional)
    """
    try:
        logging.info(f"Closing alert with deduplication key: {dedup_key}")

        # Define the payload for the Events API v2
        payload = {
            "routing_key": routing_key,
            "event_action": "resolve",  # "resolve" is used to close an alert
            "dedup_key": dedup_key,
        }

        # Add optional source if provided
        if source:
            payload["payload"] = {"source": source}

        # Send the request to PagerDuty Events API v2
        response = requests.post(
            "https://events.pagerduty.com/v2/enqueue", json=payload
        )

        # Check the response status
        if response.status_code == 202:
            logging.info("Alert successfully closed in PagerDuty.")
        else:
            logging.error(f"Failed to close alert: {response.text}")
            response.raise_for_status()

    except Exception as err:  # pylint: disable=broad-except
        traceback.print_exc()
        click.secho(f"{err}", fg="red")
        sys.exit(1)


if __name__ == "__main__":
    close_pagerduty_alert()
