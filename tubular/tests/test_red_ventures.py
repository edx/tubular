"""
Tests for the Red Ventures API functionality
"""

import ddt
import os
import logging
import unittest
from unittest import mock

import requests_mock

MAX_ATTEMPTS = int(os.environ.get("RETRY_MAX_ATTEMPTS", 5))
from tubular.red_ventures_api import (
    RedVenturesApi,
    RedVenturesException,
    RedVenturesRecoverableException,
)


@ddt.ddt
@requests_mock.Mocker()
class TestRedVentures(unittest.TestCase):
    """
    Class containing tests of all code interacting with Red Ventures.
    """

    def setUp(self):
        super().setUp()
        self.user = {"user": {"id": "1234", "original_email": "fonzie@example.com"}}
        self.red_ventures = RedVenturesApi(
            "test_audience",
            "https://test_auth_url",
            "https://test_deletion_url",
            "test_username",
            "test_password",
        )
        self.auth_token = {"access_token": "eyyyyyy.fonzie"}

    def _mock_delete(self, req_mock, status_code):
        """
        Send a mock request with dummy headers and status code.

        """
        headers = {
            "Authorization": "Bearer eyyyyyy.fonzie",
            "Content-Type": "application/json",
        }
        req_mock.delete(
            "https://test_deletion_url",
            headers=headers,
            status_code=status_code,
        )

    @mock.patch("tubular.red_ventures_api.RedVenturesApi.get_token")
    def test_delete_happy_path(self, req_mock, get_token_mock):
        """Verify status_code 204 is treated as successful"""
        self._mock_delete(req_mock, 204)
        get_token_mock.return_value = self.auth_token
        logger = logging.getLogger("tubular.red_ventures_api")
        with mock.patch.object(logger, "info") as mock_info:
            self.red_ventures.delete_user(self.user)

        self.assertEqual(
            mock_info.call_args, [("Red Ventures user deletion succeeded",)]
        )

        self.assertEqual(len(req_mock.request_history), 1)
        request = req_mock.request_history[0]
        self.assertEqual(
            request.url,
            "https://test_deletion_url/?email=fonzie%40example.com",
        )

    @mock.patch("tubular.red_ventures_api.RedVenturesApi.get_token")
    def test_delete_fatal_error(self, req_mock, get_token_mock):
        """Verify status code 400 is treated as a fatal error"""
        self._mock_delete(req_mock, 400)
        get_token_mock.return_value = self.auth_token
        message = None
        logger = logging.getLogger("tubular.red_ventures_api")
        with mock.patch.object(logger, "error") as mock_error:
            with self.assertRaises(RedVenturesException) as exc:
                self.red_ventures.delete_user(self.user)
        error = "RedVentures user deletion failed with 400 due to {message}".format(
            message=message
        )
        self.assertEqual(mock_error.call_args, [(error,)])
        self.assertEqual(str(exc.exception), error)

    @mock.patch("tubular.red_ventures_api.RedVenturesApi.get_token")
    def test_delete_fatal_error(self, req_mock, get_token_mock):
        """Verify we raise an error if there's no email address"""
        self._mock_delete(req_mock, None)
        get_token_mock.return_value = self.auth_token
        self.user = {"user": {"id": "1234"}}
        message = None
        logger = logging.getLogger("tubular.red_ventures_api")
        with mock.patch.object(logger, "error") as mock_error:
            with self.assertRaises(TypeError) as exc:
                self.red_ventures.delete_user(self.user)
        error = "Expected an email address for user to delete, but received None."
        self.assertEqual(str(exc.exception), error)

    @mock.patch("tubular.red_ventures_api.RedVenturesApi.get_token")
    def test_delete_recoverable_error(self, req_mock, get_token_mock):
        """Verify status code 500 is treated as a recoverable error"""
        self._mock_delete(req_mock, 500)
        get_token_mock.return_value = self.auth_token

        with self.assertRaises(RedVenturesRecoverableException):
            self.red_ventures.delete_user(self.user)
        self.assertEqual(len(req_mock.request_history), MAX_ATTEMPTS)
