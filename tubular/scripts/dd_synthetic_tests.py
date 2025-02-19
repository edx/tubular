#! /usr/bin/env python3

import click
import json
import logging
import os
import requests
import time
import sys

class SyntheticTest:
    '''
    Attributes for a Datadog synthetic test and its test run
    '''
    def __init__(self, name, public_id):
        self.name = name            # The test's Datadog name
        self.public_id = public_id  # The test's Datadog Test ID
        self.test_run_id = None     # The run ID given by Datadog to this test's invocation
        self.success = None

class DatadogClient:
    ''' Client class to invoke datadog API to run and monitor synthetic tests '''

    DATADOG_SYNTHETIC_TESTS_API_URL = "https://api.datadoghq.com/api/v1/synthetics/tests"

    DEPLOYMENT_TESTING_ENABLED_SWITCH = SyntheticTest(
                '''
                Deployment testing enable test governing CI/CD synthetic testing
                ''',
                "sad-hqu-h33"
            )

    def __init__(self, api_key, app_key):
        self.api_key = api_key
        self.app_key = app_key
        self.test_batch_id = None   # A 'batch' is a set of tests intended to be run in parallel
        self.trigger_time = None    # The system time at which a batch's execution was requested
        self.timeout_secs = None    # The maximum number of seconds by which time all tests must be done
        self.tests_by_public_id = {} # Dictionary mapping Datadog test ID to all info we have for a specific test

    def trigger_synthetic_tests(self, tests_to_report: [SyntheticTest]):
        '''
        Trigger running of a batch of synthetic tests.
        :param tests_to_report: List of tests to run and report on
        :return: None, but saves test info including batch ID and test run IDs in 'self'
        '''

        # Note that the list of tests to be run is one longer than the list of tests to be reported on.
        # The extra test is the so-called "deployment testing enable switch test".
        # That test should be modified via the Datadog UI to either always pass or always fail, depending
        # on whether synthetic testing is to be enabled at runtime or not, respectively.
        # While the test's result does affect how the pipeline operates, the result is not treated as reportable.
        tests_to_run = [self.DEPLOYMENT_TESTING_ENABLED_SWITCH] + tests_to_report
        self._record_requested_test_particulars(tests_to_run)
        self.trigger_time = time.time()  # Key timeouts off of this
        logging.info(f'CI batch triggered at time {self.trigger_time}')

        try:
            response = self._trigger_batch_tests()  # Kicks off asynchronous test execution for a batch of tests
            response_body = response.json()
            self._record_batch_id(response_body)    # a single batch ID has now been assiged. Save for future reference
            self._map_test_run_ids(response_body)   # one test run ID per test has been assigned. Save for reference.

        except Exception as e:
            raise Exception("Datadog error on triggering tests: " + str(e))

    def gate_on_deployment_testing_enable_switch(self):
        '''
        This is a bit hacky, but there's a designated test that's used as a deployment testing enable switch.
        If the test passes, it means that the synthetic testing GoCD pipeline is enabled, and the
        build should only proceed if all reportable tests pass; if the test fails, the build should proceed irrespective
        of any failures among the synthetic tests (which will be allowed to run, nonetheless). When this is intended,
        the GoCD pipeline responsible for running the tests should just return a success code without waiting
        for the reportable tests to complete their runs.

        :return: Nothing, but terminates task with a success code if the synthetic testing feature is disabled
        and logs the decision to skip testing on this build
        '''
        deployment_testing_enabled = self._poll_for_test_result(self.DEPLOYMENT_TESTING_ENABLED_SWITCH)
        if deployment_testing_enabled == False:
            switch_test_name = self.DEPLOYMENT_TESTING_ENABLED_SWITCH.name
            logging.warning(
                f'*** Datadog Synthetic testing disabled via failing test {switch_test_name} ***')
            sys.exit(0)

    def get_and_record_test_results(self):
        '''
        Poll for pass/fail results for all batch tests

        :return: Nothing, but saves pass/fail results in 'self'
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

    def _record_requested_test_particulars(self, test_requests):
        '''
        Save list of requested tests in this dictionary for later reference, indexed by test public ID
        '''
        for test in test_requests:
            self.tests_by_public_id[test.public_id] = test

    def _trigger_batch_tests(self):
        '''
        Ask datadog to run the set of selected synthetic tests
        returns the response from the datadog API call

        Note that using the ci (continuous integration) route leverages
        the parallel execution Datadog feature we pay extra for
        '''
        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/trigger/ci"
        headers = {
            "Content-Type": "application/json",
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }
        test_public_ids = self.tests_by_public_id.keys()
        json_request_body = {"tests": [{"public_id": public_id} for public_id in test_public_ids]}
        logging.info(f'Trigger request body: {json_request_body}')
        response = requests.post(url, headers=headers, json=json_request_body)
        if response.status_code != 200:
            raise Exception(f"Datadog API error. Status = {response.status_code}")
        return response

    def _record_batch_id(self, response_body):
        '''
        Datadog generates a single batch ID associated with the request for all the requested tests. This is distinct
        from the run ids, which are uniquely assigned to each test run.
        '''
        self.batch_id = response_body['batch_id']


    def _map_test_run_ids(self, response_body):
        '''
        Saves the test run ID values assigned by datatod to this barch request's tests, as
        a dictionary keyed off of each test's (unique) public id

        A test's public ID is assigned by Datadog when the test is created, and is entered as hard-coded
        test configuration data in this module. It is the public ids that are used in the test run results
        to identify which test is being reported on.

        While we do care as to the result for the "deployment testing enabled switch test", we use that
        result differently from all other test results, and do not save it in the dictionary
        with results we intend to report on.
        '''
        for result in response_body['results']:
            public_id = result['public_id']
            test_run_id = result['result_id']
            if public_id == self.DEPLOYMENT_TESTING_ENABLED_SWITCH.public_id:
                self.DEPLOYMENT_TESTING_ENABLED_SWITCH.test_run_id = test_run_id
            else:
                self.tests_by_public_id[public_id].test_run_id = test_run_id

    def _poll_for_test_result(self, test):
        """
        Poll every few seconds for test run results for a single, specified test, until available.

        Note that if all tests take 90 seconds or more to run, the call into this method will take 90 or
        more seconds, but subsequent calls may just take a few seconds each, depending on
        test execution time variability.

        The timeout on this operation is relative to when the batch request for test execution was made,
        not relative to the last time we polled on a test result.

        Returns None if still running; otherwise, returns True on test success and False on test failure.
        """
        test_result = None
        while test_result is None and (time.time() - self.trigger_time) < (self.timeout_secs):
            time.sleep(5)  # Poll every 5 seconds
            test_result = self._get_test_result(test)
            logging.info(f'{test_result=}')

        if test_result is None:
            raise Exception("The test run timed out.")

        completion_time = time.time()
        logging.info(f"Test {test.public_id} finished at time {completion_time} with {test_result=}")
        return test_result

    def _get_test_result(self, test):
        """
        Issue a single request to the Datadog API to fetch test results for a single, specified test.
        returns JSON structure with test results if the test run has completed; returns None otherwise
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
Command-line script to run Datadog synthetic tests in the stage environment
Automated rollback is not yet supported
"""

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

@click.command()
@click.option(
    '--enable-automated-rollbacks',
    is_flag=True,
    default=False,
    help='When set and synthetic tests fail, the most recent deployment to production is automatically rolled back'
)
@click.option(
    '--timeout',
    default=300,
    type=int,
    help='Maximum time measured in seconds for the test batch to have run to completion'
)
@click.option(
    '--tests',
    required=True,
    type=click.STRING,
    help='List of tests to be run as json with description and test_id for each test'
)
def run_synthetic_tests(enable_automated_rollbacks, timeout, tests):
    '''
    :param enable_automated_rollbacks: Failing tests trigger a rollback in the build pipeline when true
    :param timeout: Maximum number of seconds between test kick-off and completion of the slowest test
    :param tests: json encoded string with list of tests to run and report on. Each test described by name and test_id
    :return: exits thread with success or fail code indicating tests' collective success or failure (of one or more)
    '''

    if enable_automated_rollbacks:
        logging.error("Automated rollbacks are not yet supported")
        sys.exit(1)

    try:
        api_key = os.getenv("DATADOG_API_KEY_SYNTHETIC_TEST")
        app_key = os.getenv("DATADOG_APP_KEY_SYNTHETIC_TEST")
        dd_client = DatadogClient(api_key, app_key)
        dd_client.timeout_secs = timeout

        tests_as_dicts = json.loads(tests)
        tests_to_report_on = [SyntheticTest(d["name"], d["public_id"]) for d in tests_as_dicts]
        dd_client.trigger_synthetic_tests(tests_to_report_on)
        dd_client.gate_on_deployment_testing_enable_switch() # Exits summarily if test results are to be ignored
        for test in tests_to_report_on:
            logging.info(f"\t Running test {test.public_id}: {test.name}")
        dd_client.get_and_record_test_results()
        failed_tests = dd_client.get_failed_tests()

        for failed_test in failed_tests:
            logging.warning(f'Test failed: {failed_test.public_id} -- {failed_test.name}')

        task_failed_code = 1 if failed_tests else 0

    except Exception as e:
        logging.error("GoCD/Datadog integration error: ", str(e))
        task_failed_code = 1

    sys.exit(task_failed_code)

if __name__ == "__main__":
    run_synthetic_tests()
