#! /usr/bin/env python3
from dataclasses import dataclass

import click
import logging
import os
import requests
import time
import sys

class SyntheticTest:
    '''
    Attributes for a specific synthetic test and its test run under a datadog CI batch
    '''
    def __init__(self, name, public_id):
        self.name = name
        self.public_id = public_id
        self.test_run_id = None
        self.success = None

class DatadogClient:
    ''' Client class to invoke datadog API to run and monitor synthetic tests '''

    DATADOG_SYNTHETIC_TESTS_API_URL = "https://api.datadoghq.com/api/v1/synthetics/tests"
    DATADOG_SYNTHETIC_TESTS_API_URL = "https://api.datadoghq.com/api/v1/synthetics/tests"
    MAX_ALLOWABLE_TIME_SECS = 600 # 10 minutes

    def __init__(self, api_key, app_key):
        self.api_key = api_key
        self.app_key = app_key
        self.test_batch_id = None
        self.trigger_time = None
        self.tests_by_public_id = {}

    def trigger_synthetic_tests(self, test_requests: [SyntheticTest]):
        '''
        Trigger running of one or more synthetic tests.
        :param test_requests: List of tests to be run
        :return: None, but saves batch ID and test run IDs as object attributes
        '''
        self._record_batch_tests(test_requests)
        self.trigger_time = time.time()  # Key timeouts off of this
        logging.info(f'CI batch triggered at time {self.trigger_time}')

        try:
            response = self._trigger_batch_tests()
            response_body = response.json()
            self._record_batch_id(response_body)
            self._record_test_run_ids(response_body)

        except Exception as e:
            raise Exception("Datadog error on triggering tests: " + str(e))

    def get_and_record_test_results(self):
        '''
        Poll for test results for all tests that were run, and save the results
        in this datadog client object
        '''
        for test in list(self.tests_by_public_id.values()):
            test.success = self._poll_for_test_result(test)

    def get_failed_tests(self):
        '''
        Compile a list of all failed tests from the set of all tests that were run
        :return: A list of failed test objects; Empty list if all tests passed
        '''
        failed_tests = []
        for test in list(self.tests_by_public_id.values()):
            if not test.success:
                failed_tests.append(test)

        return failed_tests

    # ***************** Private methods **********************

    def _record_batch_tests(self, test_requests):
        '''
        Save list of requested tests in this datadog client object, indexed by test public ID
        '''
        for test in test_requests:
            self.tests_by_public_id[test.public_id] = test

    def _trigger_batch_tests(self):
        '''
        Ask datadog to run the set of selected synthetic tests
        returns the response from the datadog API call
        '''
        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/trigger/ci"
        headers = {
            "Content-Type": "application/json",
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }
        test_public_ids = list(self.tests_by_public_id.keys())
        json_request_body = {"tests": [{"public_id": public_id} for public_id in test_public_ids]}
        response = requests.post(url, headers=headers, json=json_request_body)
        if response.status_code != 200:
            raise Exception(f"Datadog API error. Status = {response.status_code}")
        return response

    def _record_batch_id(self, response_body):
        '''
        Saves the batch id assigned by datadog to this batch request as an object field
        '''
        self.batch_id = response_body['batch_id']


    def _record_test_run_ids(self, response_body):
        '''
        Saves the test run ID values assigned by datatod to this barch request's tests, as
        a dictionary keyed off of test public ids
        '''
        for result in response_body['results']:
            public_id = result['public_id']
            test_run_id = result['result_id']
            self.tests_by_public_id[public_id].test_run_id = test_run_id

    def _poll_for_test_result(self, test):
        """
        Poll for test run completion within the maximum allowable time for the specified test.
        Returns None if still running; otherwise, returns True on test success and False on test failure.
        """
        test_result = None
        while test_result is None and (time.time() - self.trigger_time) < (self.MAX_ALLOWABLE_TIME_SECS):
            time.sleep(5)  # Poll every 5 seconds
            test_result = self._get_test_result(test)

        if test_result is None:
            raise Exception("The test run timed out.")

        completion_time = time.time()
        logging.info(f"Test {test.public_id} finished at time {completion_time} with {test_result=}")
        return test_result

    def _get_test_result(self, test):
        """
        returns JSON structure with test results for all tests in the test run
        if the test run has completed; returns None otherwise
        """
        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/{test.public_id}/results/{test.test_run_id}"
        headers = {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None

        response_json = response.json()
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

        tests_to_run = [
                        SyntheticTest(
                            '''
                            edX Smoke Test - [Anonymous user] An anonymous user is directed to the
                            Logistration page (authn.edx.org) when trying to access content behind log-in wall
                            ''',
                            "6tq-u28-hwa"
                        ),
                        SyntheticTest(
                             '''
                             edX Smoke Test - [Unenrolled student] An unenrolled student cannot load a
                             course’s landing page, and sees the “Enroll Now” screen
                             ''',
                             "zkx-36f-kui"
                        ),
                        SyntheticTest(
                             '''
                             [Synthetics] edX Smoke Test - [Audit student] An enrolled audit student can access
                             a course’s landing page, course content, and course forum
                             ''',
                             "jvx-2jw-agj"
                        ),
                        SyntheticTest(
                            '''
                            [Synthetics] edX Smoke Test - [Audit student] An enrolled audit student cannot load
                            a graded problem, and sees the upsell screen
                            ''',
                            "75p-sez-5wg"
                        ),
                        SyntheticTest(
                            '''
                            [Synthetics] edX Smoke Test - [Verified student] An enrolled verified student can
                            access a course’s landing page, course content, and course forum
                            ''',
                            "zbz-r28-jjx"
                        ),
                        SyntheticTest(
                            '''
                            [Synthetics] edX Smoke Test - [Verified student] A verified student can
                            access a graded course problem
                            ''',
                            "tck-hrr-ubp"
                        ),
                        ]
        logging.info(f"Running the following tests: {str(tests_to_run)}")
        dd_client.trigger_synthetic_tests(tests_to_run)
        dd_client.get_and_record_test_results()
        failed_tests = dd_client.get_failed_tests()

        for failed_test in failed_tests:
            logging.warning(f'Test {failed_test.name}({failed_test.public_id} failed')

        task_failed_code = 1 if failed_tests else 0

    except Exception as e:
        logging.error("GoCD/Datadog integration error: ", str(e))
        task_failed_code = 1

    sys.exit(task_failed_code)

if __name__ == "__main__":
    run_synthetic_tests(False, None)   # pylint: disable=no-value-for-parameter
