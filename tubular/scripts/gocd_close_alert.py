"""
Command-line script to close any existing alert for a GoCD pipeline.

Picks up pipeline details from GoCD environment variables to derive the alias
field. (See `close_opsgenie_alert.py` for a version that allows full control
of the alias.)

This script is intended to be used with the "API - GoCD Integration" integration
in Jira Service Management (previously Opsgenie):

https://2u-internal.atlassian.net/jira/settings/products/ops/integrations/API/c15f0e6a-e15d-4659-ab1e-e0854c5fb5dc
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
    help="Integration API key to use for JSM Alerts API",
)
def gocd_close_alert(auth_token):
    """
    Close a JSM alert, if it exists, using GoCD environment variables.
    """
    pipeline = os.environ['GO_PIPELINE_NAME']
    stage = os.environ['GO_STAGE_NAME']
    job = os.environ['GO_JOB_NAME']

    # This has to match the format in tubular.scripts.gocd_open_alert because
    # the open alert will be discovered by its alias.
    alias = f'gocd-pipeline-{pipeline}-{stage}-{job}'

    log.info(f"Closing alert in JSM with alias {alias}")
    opsgenie = opsgenie_api.OpsGenieAPI(auth_token)
    opsgenie.close_opsgenie_alert_by_alias(alias, source='tubular.scripts.gocd_close_alert')


if __name__ == '__main__':
    gocd_close_alert()
