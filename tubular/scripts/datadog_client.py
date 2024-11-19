from dataclasses import dataclass

import requests
import time


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
        url = f"{self.DATADOG_SYNTHETIC_TESTS_API_URL}/trigger/ci"
        headers = {
            "Content-Type": "application/json",
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }
        # TODO: For Hello, world exercise, just run one test; in general, need to run all of them
        json_request_body = {"tests": [{"public_id": test_requests[0].test_id}]}

        response = requests.post(url, headers=headers, json=json_request_body)

        if response.status_code != 200:
            raise Exception("Datadog API error")

        try:
            response_body = response.json()
            result = response_body['results'][0]
            aggregate_test_run_id = result['result_id']
            return aggregate_test_run_id

        raise Exception("Unexpected Datadog results")

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
            json_test_run_results = self._wait_for_test(test_run_id, request.test_id)

        return json_test_run_results  # TODO: Create and return array of results; don't just return the last one

    def _wait_for_test(self, test_run_id, test_id):
        """
        Poll for aggregate test run completion within the maximum allowable time.
        Returns the JSON structure with all test run results.
        """
        start_time = time.time()
        json_test_on_test_run_result = None
        while json_test_on_test_run_result is None and (time.time() - start_time) < (self.MAX_ALLOWABLE_TIME_SECS):
            time.sleep(5)  # Poll every 5 seconds
            print("Testing on DD result")
            json_test_on_test_run_result = self._get_json_test_on_test_run_result(test_run_id, test_id)

        if json_test_on_test_run_result is None:
            raise Exception("The test run timed out.")

        return json_test_on_test_run_result

    def _get_json_test_on_test_run_result(self, test_run_id, test_id):
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
        return self._get_pass_fail_result(response_json, test_run_id)

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
            test_run_data = result[0]['result']
            pass_fail = test_run_data['passed']
            return pass_fail

        raise Exception("Failed to find test result in test run")


