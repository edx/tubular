#! /usr/bin/env python3
from dataclasses import dataclass

import click
import logging
import os
import requests
import time
import sys

@dataclass
class SyntheticTestRequest:
    '''
    Data Transfer Object (DTO) for requesting that a predefined Datadog synthetic test be run
    '''
    test_name: str
    test_id: str


class DatadogClient:
    ''' Invokes datadog API to run and monitor synthetic tests '''

    DATADOG_SYNTHETIC_TESTS_API_URL = "https://api.datadoghq.com/api/v1/synthetics/tests"
    MAX_ALLOWABLE_TIME_SECS = 60 # 1 minute

    def __init__(self, api_key, app_key):
        self.api_key = api_key
        self.app_key = app_key

    def trigger_synthetic_tests(self, test_requests: [SyntheticTestRequest]) -> str:
        '''
        Trigger running one or more synthetic tests.
        :param test_requests: List of tests to be run
        :return: An opaque aggregate run request identifier
        '''
        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/trigger"
        headers = {
            "Content-Type": "application/json",
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }
        # TODO: For Hello, world exercise, just run one test; in general, need to run all of them
        json_request_body = {"tests": [{"public_id": test_requests[0].test_id}]}

        response = requests.post(url, headers=headers, json=json_request_body)

        if response.status_code != 200:
            raise Exception(f"Datadog API error. Status = {response.status_code}")

        try:
            response_body = response.json()
            result = response_body['results'][0]
            aggregate_test_run_id = result['result_id']
            return aggregate_test_run_id

        except Exception as e:
            raise Exception("Unexpected Datadog results: " + str(e))

    def get_test_results(self, test_run_id, test_requests):
        '''
        Poll for completion of all tests triggered as part of the "test_run_id" test run
        :param test_run_id: Opaque identifier for the aggregate test run
        :param test_requests: A list of the tests that were requested with this aggregate test run
        :return: Currently, just a True/False bool for the last test in the aggregate test run; TODO - return
                a dictionary of results with results for all the tests that ran
        '''
        json_test_run_results = None
        for request in test_requests:
            json_test_run_results = self._get_result_via_polling(test_run_id, request.test_id)

        return json_test_run_results  # TODO: Create and return array of results; don't just return the last one

    def _get_result_via_polling(self, test_run_id, test_id):
        """
        Poll for aggregate test run completion within the maximum allowable time.
        Returns the JSON structure with all test run results.
        """
        start_time = time.time()
        single_test_json_result = None
        while single_test_json_result is None and (time.time() - start_time) < (self.MAX_ALLOWABLE_TIME_SECS):
            time.sleep(5)  # Poll every 5 seconds
            logging.info("*** Testing whether DD result is available ***")
            single_test_json_result = self._get_single_test_json_result(test_run_id, test_id)

        if single_test_json_result is None:
            raise Exception("The test run timed out.")

        logging.info("*** Test result found ***")
        return single_test_json_result

    def _get_single_test_json_result(self, test_run_id, test_id):
        """
        returns JSON structure if test run has completed; returns None otherwise
        """
        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/{test_id}/results"
        headers = {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return None

        response_json = response.json()
        logging.info(f"*** {test_run_id=} ***")
        return response_json
        # return self._get_pass_fail_result(response_json, test_run_id)

    @staticmethod
    def _json_get_test_run_id(json_response):
        """
        Extract test run ID from trigger test run result.
        """
        key = "result_id"
        if key in json_response:
            return json_response[key]
        raise Exception("Trigger request failed")

    @staticmethod
    def _get_pass_fail_result(input_json, test_run_id):
        """
        Extracts pass/fail result from the specific test run in the aggregate test run result set
        """
        aggregate_results = input_json['results']
        result = [r for r in aggregate_results if r['result_id'] == test_run_id]
        if result is not None:
            test_run_data = result['result']
            logging.info(f"*** Found result for {test_run_id=}: {test_run_data} ***")
            pass_fail = test_run_data['passed']
            return pass_fail

        raise Exception("Failed to find test result in test run")


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
    PUBLIC_TEST_ID = "sad-hqu-h33"

    logging.info("****** In run_synthetic_tests")

    if enable_automated_rollbacks:
        logging.Error("Automated rollbacks are not yet supported")
        sys.exit(1)

    try:
        # Will use the Datadog API to run synthetic tests
        api_key = os.getenv("DATADOG_API_KEY")
        app_key = os.getenv("DATADOG_APP_KEY")
        dd_client = DatadogClient(api_key, app_key)

        # Prepare and trigger the synthetic test request
        test_requests = [SyntheticTestRequest("Hello, world test", PUBLIC_TEST_ID)]
        logging.info("*** Triggering synthetic tests ***")
        test_run_id = dd_client.trigger_synthetic_tests(test_requests)

        # Fetch and print the test results
        logging.info("*** Getting test results ***")
        test_results = dd_client.get_test_results(test_run_id, test_requests)
        logging.info("****** Test results:", str(test_results))

    except Exception as e:
        print("An error occurred:", str(e))
        exit()

    return "Datadog synthetic test ran"

if __name__ == "__main__":
    run_synthetic_tests(False, None)   # pylint: disable=no-value-for-parameter
