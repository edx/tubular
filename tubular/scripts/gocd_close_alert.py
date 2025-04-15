"""
Command-line script to close any existing alert for a GoCD pipeline.

This is like close_opsgenie_alert.py except it picks up pipeline details from
environment variables to automatically create the alias field.
"""

import logging
import os

import click

import tubular.opsgenie_api as opsgenie_api

log = logging.getLogger(__name__)


@click.command('gocd_close_alert')
@click.option(
    '--auth-token',
    required=True,
    help="Authentication token to use for JSM Alerts API",
)
def gocd_close_alert(auth_token):
    """
    Create an OpsGenie alert

    Arguments:
        auth_token: API token for Opsgenie/JSM
        responders: The team responsible for the alert
    """
    pipeline = os.environ['GO_PIPELINE_NAME']
    stage = os.environ['GO_STAGE_NAME']
    job = os.environ['GO_JOB_NAME']

    # This has to match the format in tubular.scripts.gocd_open_alert because
    # the open alert will be discovered by its alias.
    alias = f'gocd-pipeline-{pipeline}-{stage}-{job}'

    log.info(f"Closing alert {alias} on Opsgenie")
    opsgenie = opsgenie_api.OpsGenieAPI(auth_token)
    opsgenie.close_opsgenie_alert_by_alias(alias, source='tubular.scripts.gocd_close_alert')


if __name__ == '__main__':
    gocd_close_alert()
