"""
Tests for the Salesforce Marketing Cloud API functionality
"""

import ddt
import os
import logging
import unittest
from unittest import mock

import requests_mock

os.environ['RETRY_SFMC_MAX_ATTEMPTS'] = '2'
from tubular.salesforce_marketing_cloud_api import (
    SalesforceMarketingCloudApi,
    SalesforceMarketingCloudException,
    SalesforceMarketingCloudRecoverableException,
)


@ddt.ddt
@requests_mock.Mocker()
class TestSalesforceMarketingCloud(unittest.TestCase):
    """
    Class containing tests of all code interacting with Salesforce Marketing Cloud.
    """

    def setUp(self):
        super().setUp()
        self.learner = {'user': {'id': 1234}}
        self.sfmc = SalesforceMarketingCloudApi(
            'test-client-id',
            'test-client-secret',
            'test-subdomain',
            'test-account-id'
        )
        self.token_url = 'https://test-subdomain.auth.marketingcloudapis.com/v2/token'
        self.delete_url = 'https://test-subdomain.rest.marketingcloudapis.com/hub/v1/dataevents/key:Contacts_for_Delete/rowset'
        self.access_token = 'test-access-token-12345'

    def _mock_token_request(self, req_mock, status_code=200, access_token=None):
        if access_token is None:
            access_token = self.access_token
        
        req_mock.post(
            self.token_url,
            json={'access_token': access_token} if status_code == 200 else {},
            status_code=status_code
        )

    def _mock_delete_request(self, req_mock, status_code=200, response_json=None):
        req_mock.post(
            self.delete_url,
            json=response_json if response_json else {},
            status_code=status_code
        )

    def test_delete_user_happy_path(self, req_mock):
        self._mock_token_request(req_mock)
        self._mock_delete_request(req_mock, 200)

        logger = logging.getLogger('tubular.salesforce_marketing_cloud_api')
        with mock.patch.object(logger, 'info') as mock_info:
            self.sfmc.delete_user(self.learner)

        self.assertTrue(mock_info.called)
        self.assertIn('SFMC user deletion succeeded', str(mock_info.call_args))
        self.assertIn('1234', str(mock_info.call_args))

        self.assertEqual(len(req_mock.request_history), 2)
        
        token_request = req_mock.request_history[0]
        self.assertEqual(token_request.json(), {
            'grant_type': 'client_credentials',
            'client_id': 'test-client-id',
            'client_secret': 'test-client-secret'
        })

        delete_request = req_mock.request_history[1]
        self.assertEqual(delete_request.headers['Authorization'], f'Bearer {self.access_token}')
        request_data = delete_request.json()[0]
        self.assertEqual(request_data['keys']['SubscriberKey'], '1234')
        self.assertIs(request_data['values']['IsDelete'], True)

    def test_delete_user_missing_user_id(self, req_mock):
        learner = {'user': {}}
        
        with self.assertRaises(TypeError) as exc:
            self.sfmc.delete_user(learner)
        
        self.assertEqual(
            str(exc.exception),
            'Expected a user ID for user to delete, but received None.'
        )

    def test_delete_fatal_error(self, req_mock):
        self._mock_token_request(req_mock)
        self._mock_delete_request(req_mock, status_code=400, response_json={'error': 'Bad Request'})

        logger = logging.getLogger('tubular.salesforce_marketing_cloud_api')
        with mock.patch.object(logger, 'error') as mock_error:
            with self.assertRaises(SalesforceMarketingCloudException):
                self.sfmc.delete_user(self.learner)

        self.assertTrue(mock_error.called)
        error_message = str(mock_error.call_args)
        self.assertIn('SFMC user deletion failed', error_message)
        self.assertIn('400', error_message)

    @ddt.data(429, 500)
    def test_delete_recoverable_error(self, status_code, req_mock):
        self._mock_token_request(req_mock)
        self._mock_delete_request(req_mock, status_code=status_code)

        with self.assertRaises(SalesforceMarketingCloudRecoverableException):
            self.sfmc.delete_user(self.learner)

        self.assertGreaterEqual(len(req_mock.request_history), 2)
