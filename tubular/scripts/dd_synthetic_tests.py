#! /usr/bin/env python3
from dataclasses import dataclass

import click
import logging
import os
import sys

from datadog_client import DatadogClient
from datadog_client import SyntheticTestRequest

"""
Command-line script to run Datadog synthetic tests in the production enviornment and then slack notify and/or roll back
"""
@click.option(
    '--enable-automated-rollbacks',
    is_flag=True,
    default=False,
    help='When set and synthetic tests fail, the most recent deployment to production is automatically rolled back'
)
@click.option(
    '--slack-notification-channel',
    required=False,
    help='When set and synthetic tests fail, an alert Slack message is sent to this channel'
)

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

def run_synthetic_tests(enable_automated_rollbacks, slack_notification_channel):
    '''

    :param enable_automated_rollbacks:
    :param slack_notification_channel:
    :return:
    '''
    PUBLIC_TEST_ID = "sad-hqu-h33"

    if enable_automated_rollbacks:
        logging.Error("Automated rollbacks are not yet supported")
        exit()

    try:
        # Will use the Datadog API to run synthetic tests
        api_key = os.getenv("DATADOG_API_KEY")
        app_key = os.getenv("DATADOG_APP_KEY")
        dd_client = DatadogClient(api_key, app_key)

        # Prepare and trigger the synthetic test request
        test_requests = [SyntheticTestRequest("Hello, world test", PUBLIC_TEST_ID)]
        test_run_id = dd_client.trigger_synthetic_tests(test_requests)

        # Fetch and print the test results
        test_results = dd_client.get_test_results(test_run_id, test_requests)
        print("Test results:", test_results)

    except Exception as e:
        print("An error occurred:", str(e))
        exit()

    return "Datadog synthetic test ran"

if __name__ == "__main__":
    run_synthetic_tests()   # pylint: disable=no-value-for-parameter
