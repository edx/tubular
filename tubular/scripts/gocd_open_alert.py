"""
Command-line script to create an alert for a GoCD pipeline.

This is like alert_opsgenie.py except it picks up pipeline details from
environment variables to automatically create the alias, message, and
description fields.
"""

import logging
import os

import click

import tubular.opsgenie_api as opsgenie_api

log = logging.getLogger(__name__)


@click.command('gocd_open_alert')
@click.option(
    '--auth-token',
    required=True,
    help="Authentication token to use for JSM Alerts API",
)
@click.option(
    '--responders',
    required=True,
    help="Name of JSM to page for this alert",
)
def gocd_open_alert(auth_token, responders):
    """
    Create an OpsGenie alert

    Arguments:
        auth_token: API token for Opsgenie/JSM
        responders: The team responsible for the alert
    """
    pipeline = os.environ['GO_PIPELINE_NAME']
    pipeline_counter = os.environ['GO_PIPELINE_COUNTER']
    stage = os.environ['GO_STAGE_NAME']
    stage_counter = os.environ['GO_STAGE_COUNTER']
    job = os.environ['GO_JOB_NAME']
    trigger_user = os.environ['GO_TRIGGER_USER']

    job_url = f'https://gocd.tools.edx.org/go/tab/build/detail/{pipeline}/{pipeline_counter}/{stage}/{stage_counter}/{job}'

    alias = f'gocd-pipeline-{pipeline}-{stage}-{job}'
    message = f"[GoCD] Build Failed on {pipeline}"
    description = f"Pipeline {pipeline} failed. Please see the build logs: {job_url} (triggered by {trigger_user})"

    log.info("Creating alert on Opsgenie")
    opsgenie = opsgenie_api.OpsGenieAPI(auth_token)
    opsgenie.alert_opsgenie(message, description, responders, alias=alias)


if __name__ == '__main__':
    gocd_open_alert()
