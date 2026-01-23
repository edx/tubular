"""
Tests for the Salesforce Marketing Cloud API functionality
"""

import ddt
import logging
import os
from unittest import TestCase, mock

import requests_mock

os.environ['RETRY_SFMC_MAX_ATTEMPTS'] = '2'
from tubular.salesforce_marketing_cloud_api import (
    SalesforceMarketingCloudApi,
    SalesforceMarketingCloudException,
    SalesforceMarketingCloudRecoverableException,
)


@ddt.ddt
@requests_mock.Mocker()
class TestSalesforceMarketingCloud(TestCase):
    """
    Class containing tests of all code interacting with Salesforce Marketing Cloud.
    """

    def setUp(self):
        super().setUp()
        self.learner = {'original_email': 'test@example.com'}
        self.contact_key = 'test-contact-key-12345'
        self.sfmc = SalesforceMarketingCloudApi(
            'test-client-id',
            'test-client-secret',
            'test-subdomain'
        )
        self.token_url = 'https://test-subdomain.auth.marketingcloudapis.com/v2/token'
        self.search_url = 'https://test-subdomain.rest.marketingcloudapis.com/contacts/v1/addresses/email/search'
        self.delete_url = 'https://test-subdomain.rest.marketingcloudapis.com/contacts/v1/contacts/actions/delete?type=keys'
        self.access_token = 'test-access-token-12345'

    def _mock_token_request(self, req_mock, status_code=200, access_token=None):
        if access_token is None:
            access_token = self.access_token
        
        req_mock.post(
            self.token_url,
            json={'access_token': access_token} if status_code == 200 else {},
            status_code=status_code
        )

    def _mock_search_request(self, req_mock, status_code=200, contact_key=None, response_json=None):
        if response_json is None and status_code == 200:
            if contact_key:
                response_json = {
                    'channelAddressResponseEntities': [
                        {
                            'contactKeyDetails': [
                                {
                                    'contactKey': contact_key,
                                    'createDate': '2025-06-18T12:22:00'
                                }
                            ],
                            'channelAddress': self.learner['original_email']
                        }
                    ],
                    'requestServiceMessageID': 'test-request-id',
                    'responseDateTime': '2026-01-21T04:18:54.7797351-06:00',
                    'resultMessages': [],
                    'serviceMessageID': 'test-service-id'
                }
            else:
                # No contact found
                response_json = {
                    'channelAddressResponseEntities': [],
                    'requestServiceMessageID': 'test-request-id',
                    'responseDateTime': '2026-01-21T04:18:54.7797351-06:00',
                    'resultMessages': [],
                    'serviceMessageID': 'test-service-id'
                }
        
        req_mock.post(
            self.search_url,
            json=response_json if response_json else {},
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
        self._mock_search_request(req_mock, contact_key=self.contact_key)
        self._mock_delete_request(req_mock, 200)

        logger = logging.getLogger('tubular.salesforce_marketing_cloud_api')
        with mock.patch.object(logger, 'info') as mock_info:
            self.sfmc.delete_user(self.learner)

        self.assertTrue(mock_info.called)
        info_calls = [str(call) for call in mock_info.call_args_list]
        self.assertTrue(any('SFMC user deletion succeeded' in call for call in info_calls))
        self.assertTrue(any(self.contact_key in call for call in info_calls))

        self.assertEqual(len(req_mock.request_history), 3)
        
        token_request = req_mock.request_history[0]
        self.assertEqual(token_request.json(), {
            'grant_type': 'client_credentials',
            'client_id': 'test-client-id',
            'client_secret': 'test-client-secret'
        })

        search_request = req_mock.request_history[1]
        self.assertEqual(search_request.headers['Authorization'], f'Bearer {self.access_token}')
        search_data = search_request.json()
        self.assertEqual(search_data['ChannelAddressList'], ['test@example.com'])
        self.assertEqual(search_data['MaximumCount'], 5)

        delete_request = req_mock.request_history[2]
        self.assertEqual(delete_request.headers['Authorization'], f'Bearer {self.access_token}')
        delete_data = delete_request.json()
        self.assertEqual(delete_data['values'], [self.contact_key])
        self.assertEqual(delete_data['DeleteOperationType'], 'ContactAndAttributes')

    def test_delete_user_no_contact_found(self, req_mock):
        self._mock_token_request(req_mock)
        self._mock_search_request(req_mock, contact_key=None)  # No contact found

        logger = logging.getLogger('tubular.salesforce_marketing_cloud_api')
        with mock.patch.object(logger, 'info') as mock_info:
            self.sfmc.delete_user(self.learner)

        self.assertTrue(mock_info.called)
        info_calls = [str(call) for call in mock_info.call_args_list]
        self.assertTrue(any('No contact found' in call for call in info_calls))

        self.assertEqual(len(req_mock.request_history), 2)

    def test_delete_user_missing_email(self, req_mock):
        learner = {}
        
        with self.assertRaises(TypeError) as context:
            self.sfmc.delete_user(learner)
        
        self.assertIn('email is required', str(context.exception))

    def test_search_fatal_error(self, req_mock):
        self._mock_token_request(req_mock)
        self._mock_search_request(req_mock, status_code=400, response_json={'error': 'Bad Request'})

        logger = logging.getLogger('tubular.salesforce_marketing_cloud_api')
        with mock.patch.object(logger, 'error') as mock_error:
            with self.assertRaises(SalesforceMarketingCloudException):
                self.sfmc.delete_user(self.learner)

        self.assertTrue(mock_error.called)
        error_message = str(mock_error.call_args)
        self.assertIn('SFMC contact search failed', error_message)
        self.assertIn('400', error_message)

    def test_delete_fatal_error(self, req_mock):
        self._mock_token_request(req_mock)
        self._mock_search_request(req_mock, contact_key=self.contact_key)
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
    def test_search_recoverable_error(self, status_code, req_mock):
        self._mock_token_request(req_mock)
        self._mock_search_request(req_mock, status_code=status_code)

        with self.assertRaises(SalesforceMarketingCloudRecoverableException):
            self.sfmc.delete_user(self.learner)

        self.assertGreaterEqual(len(req_mock.request_history), 2)

    @ddt.data(429, 500)
    def test_delete_recoverable_error(self, status_code, req_mock):
        self._mock_token_request(req_mock)
        self._mock_search_request(req_mock, contact_key=self.contact_key)
        self._mock_delete_request(req_mock, status_code=status_code)

        with self.assertRaises(SalesforceMarketingCloudRecoverableException):
            self.sfmc.delete_user(self.learner)

        self.assertGreaterEqual(len(req_mock.request_history), 3)

    def test_token_fatal_error(self, req_mock):
        self._mock_token_request(req_mock, status_code=401)

        logger = logging.getLogger('tubular.salesforce_marketing_cloud_api')
        with mock.patch.object(logger, 'error') as mock_error:
            with self.assertRaises(SalesforceMarketingCloudException):
                self.sfmc.delete_user(self.learner)

        self.assertTrue(mock_error.called)
        self.assertIn('SFMC token request failed', str(mock_error.call_args))

    @ddt.data(429, 500)
    def test_token_recoverable_error(self, status_code, req_mock):
        self._mock_token_request(req_mock, status_code=status_code)

        with self.assertRaises(SalesforceMarketingCloudRecoverableException):
            self.sfmc.delete_user(self.learner)

        # Should have retried with backoff
        self.assertGreaterEqual(len(req_mock.request_history), 2)
