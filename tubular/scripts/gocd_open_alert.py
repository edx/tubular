"""
Command-line script to create an alert for a GoCD pipeline.

Picks up pipeline details from GoCD environment variables to derive the alias,
message, and description fields.  (See `alert_opsgenie.py` for a version that
allows full control of those fields.)

This script is intended to be used with the "API - GoCD Integration" integration
in Jira Service Management (previously Opsgenie):

https://2u-internal.atlassian.net/jira/settings/products/ops/integrations/API/c15f0e6a-e15d-4659-ab1e-e0854c5fb5dc
"""

import logging
import os
import sys

import click

import tubular.opsgenie_api as opsgenie_api

log = logging.getLogger(__name__)


@click.command('gocd_open_alert')
@click.option(
    '--auth-token',
    required=True,
    help="Integration API key to use for JSM Alerts API",
)
@click.option(
    '--responder',
    required=True,
    help="Name of JSM team to page",
)
@click.option(
    '--runbook',
    required=False,
    help="URL of runbook to offer in alert",
)
def gocd_open_alert(auth_token, responder, runbook):
    """
    Create an alert in JSM using GoCD environment variables.
    """
    # Guard against a templated call to this script passing in an undefined
    # variable (empty string). We would rather fail this call than silently
    # create an alert that no one will see.
    if not responder:
        log.error("Responder field was empty -- refusing to create alert.")
        sys.exit(1)

    pipeline = os.environ['GO_PIPELINE_NAME']
    pipeline_counter = os.environ['GO_PIPELINE_COUNTER']
    stage = os.environ['GO_STAGE_NAME']
    stage_counter = os.environ['GO_STAGE_COUNTER']
    job = os.environ['GO_JOB_NAME']
    trigger_user = os.environ['GO_TRIGGER_USER']

    job_url = f'https://gocd.tools.edx.org/go/tab/build/detail/{pipeline}/{pipeline_counter}/{stage}/{stage_counter}/{job}'

    # The integration will create alerts when the alias field starts with
    # `gocd-pipeline-`. The entire alias should also be identical to the
    # string produced by gocd_close_alert.py.
    alias = f'gocd-pipeline-{pipeline}-{stage}-{job}'
    message = f"[GoCD] Pipeline failed: {pipeline}/{stage}/{job}"
    description = (
        f"Pipeline {pipeline} failed.\n\n"
        f"- Runbook: {runbook or '<not provided>'}\n"
        f"- Build logs: {job_url}\n"
        f"- Triggered by: {trigger_user}\n"
    )

    log.info(f"Creating alert in JSM with alias {alias}")
    opsgenie = opsgenie_api.OpsGenieAPI(auth_token)
    opsgenie.alert_opsgenie(message, description, responder, alias=alias)


if __name__ == '__main__':
    gocd_open_alert()
