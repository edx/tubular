#! /usr/bin/env python3
from dataclasses import dataclass

import click
import json
import logging
import os
import pprint
import requests
import time
import sys

class DatadogClient:
    ''' Invokes datadog API to run and monitor synthetic tests '''

    DATADOG_SYNTHETIC_TESTS_API_URL = "https://api.datadoghq.com/api/v1/synthetics/tests"
    DATADOG_SYNTHETIC_TESTS_API_URL = "https://api.datadoghq.com/api/v1/synthetics/tests"
    MAX_ALLOWABLE_TIME_SECS = 1200 # 20 minutes

    def __init__(self, api_key, app_key):
        self.api_key = api_key
        self.app_key = app_key
        self.test_run_id = None
        self.trigger_time = None

    def trigger_synthetic_tests(self, test_requests: [dict]) -> str:
        '''
        Trigger running of one or more synthetic tests.
        :param test_requests: List of tests to be run
        :return: None, but saves opaque test run ID as object attribute
        '''
        if self.test_run_id:
            raise Exception("Datadog error: tests already triggered")

        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/trigger/ci"
        headers = {
            "Content-Type": "application/json",
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }
        json_request_body = {"tests": [{"public_id": t['id']} for t in test_requests]}
        response = requests.post(url, headers=headers, json=json_request_body)

        if response.status_code != 200:
            raise Exception(f"Datadog API error. Status = {response.status_code}")

        try:
            response_body = response.json()
            result = response_body['results'][0]
            aggregate_test_run_id = result['result_id']
            logging.info(f"Datadog test run launched: {aggregate_test_run_id}")
            self.test_run_id = aggregate_test_run_id
            self.trigger_time = time.time() # Key timeouts off of this

        except Exception as e:
            raise Exception("Datadog error on triggering tests: " + str(e))

    def get_failed_tests(self, test_requests):
        '''
        Poll for completion of all tests triggered as part of the "test_run_id" test run
        :param test_run_id: Opaque identifier for the aggregate test run
        :return: A list of the test ids for the tests that failed; Empty list if all tests passed
        '''
        failed_tests = []
        for test in test_requests:
            test_result = self._poll_for_test_result(test['id'])
            if test_result == False:
                failed_tests.append(test)

        return failed_tests

    # ***************** Private methods **********************

    def _poll_for_test_result(self, test_id):
        """
        Poll for test run completion within the maximum allowable time for the specified test.
        Returns None if still running; otherwise, returns True on test success and False on test failure.
        """
        start_time = time.time()
        test_result = None
        while test_result is None and (time.time() - self.trigger_time) < (self.MAX_ALLOWABLE_TIME_SECS):
            time.sleep(5)  # Poll every 5 seconds
            test_result = self._get_test_result(test_id)

        if test_result is None:
            raise Exception("The test run timed out.")

        return test_result

    def _get_test_result(self, test_id):
        """
        returns JSON structure with test results for all tests in the test run
        if the test run has completed; returns None otherwise
        """
        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/{test_id}/results/{self.test_run_id}"
        headers = {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return None

        response_json = response.json()
        logging.info(f"Response for test {test_id} = {response_json['result']}")
        return response_json['result']['passed']

"""
Command-line script to run Datadog synthetic tests in the production enviornment and then slack notify and/or roll back
"""

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

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

def run_synthetic_tests(enable_automated_rollbacks, slack_notification_channel):
    '''
    :param enable_automated_rollbacks:
    :param slack_notification_channel:
    :return:
    '''
    if enable_automated_rollbacks:
        logging.Error("Automated rollbacks are not yet supported")
        sys.exit(1)

    try:
        # Will use the Datadog API to run synthetic tests
        api_key = os.getenv("DATADOG_API_KEY")
        app_key = os.getenv("DATADOG_APP_KEY")
        dd_client = DatadogClient(api_key, app_key)

        # Prepare and trigger the synthetic test request
        # PUBLIC_TEST_ID = "sad-hqu-h33"
        # tests_to_run = json.loads(os.getenv("TESTS_TO_RUN"))
        tests_to_run = [
                        {
                            "name":
                             '''
                             edX Smoke Test - [Anonymous user] An anonymous user is directed to the
                             Logistration page (authn.edx.org) when trying to access content behind log-in wall
                             ''',
                            "id": "6tq-u28-hwa"
                         },
                        {
                            "name":
                             '''
                             edX Smoke Test - [Unenrolled student] An unenrolled student cannot load a
                             course’s landing page, and sees the “Enroll Now” screen
                             ''',
                             "id": "zkx-36f-kui"
                        },
                        {
                            "name":
                             '''
                             [Synthetics] edX Smoke Test - [Audit student] An enrolled audit student can access
                             a course’s landing page, course content, and course forum
                             ''',
                             "id": "jvx-2jw-agj"
                        },
                        # {
                        #     "name":
                        #     '''
                        #     [Synthetics] edX Smoke Test - [Audit student] An enrolled audit student cannot load
                        #     a graded problem, and sees the upsell screen
                        #     ''',
                        #      "id": "75p-sez-5wg"
                        # },
                        # {
                        #     "name":
                        #         '''
                        #         [Synthetics] edX Smoke Test - [Verified student] An enrolled verified student can
                        #         access a course’s landing page, course content, and course forum
                        #         ''',
                        #     "id": "zbz-r28-jjx"
                        # },
                        # {
                        #     "name":
                        #         '''
                        #         [Synthetics] edX Smoke Test - [Verified student] A verified student can
                        #         access a graded course problem
                        #         ''',
                        #     "id": "tck-hrr-ubp"
                        # },
                        ]
        logging.info(f"Running the following tests: {str(tests_to_run)}")

        dd_client.trigger_synthetic_tests(tests_to_run)

        failed_tests = dd_client.get_failed_tests(tests_to_run)
        for failed_test in failed_tests:
            logging.warning(f'Test {failed_test["name"]}({failed_test["id"]}) failed')

        task_failed_code = 1 if failed_tests else 0

    except Exception as e:
        logging.error("GoCD/Datadog integration error: ", str(e))
        task_failed_code = 1

    sys.exit(task_failed_code)

if __name__ == "__main__":
    run_synthetic_tests(False, None)   # pylint: disable=no-value-for-parameter
