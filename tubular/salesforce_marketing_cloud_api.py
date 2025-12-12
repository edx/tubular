"""
Salesforce Marketing Cloud API class that is used to delete user from SFMC.
"""

import logging
import os

import backoff
import requests

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = int(os.environ.get("RETRY_SFMC_MAX_ATTEMPTS", 5))


class SalesforceMarketingCloudException(Exception):
    """
    SalesforceMarketingCloudException will be raised when there is a fatal error and is not recoverable.
    """

    pass


class SalesforceMarketingCloudRecoverableException(SalesforceMarketingCloudException):
    """
    SalesforceMarketingCloudRecoverableException will be raised when request can be retryable.
    """

    pass


class SalesforceMarketingCloudApi:
    """
    Salesforce Marketing Cloud API is used to handle communication with SFMC APIs.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        subdomain: str,
        account_id: str,
    ):
        """
        Initialize the SFMC API client.

        Args:
            client_id: SFMC OAuth client ID
            client_secret: SFMC OAuth client secret
            subdomain: SFMC subdomain (e.g., 'mc123456789')
            account_id: SFMC account/MID identifier
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.subdomain = subdomain
        self.account_id = account_id
        self.token_host = f"{subdomain}.auth.marketingcloudapis.com"
        self.suppression_host = f"{subdomain}.rest.marketingcloudapis.com"
        self._access_token = None

    @backoff.on_exception(
        backoff.expo,
        SalesforceMarketingCloudRecoverableException,
        max_tries=MAX_ATTEMPTS,
    )
    def _get_access_token(self) -> str:
        """
        Obtain an OAuth access token from SFMC.

        Returns:
            str: Access token for API requests

        Raises:
            SalesforceMarketingCloudException: if the error from SFMC is unrecoverable/unretryable.
            SalesforceMarketingCloudRecoverableException: if the error from SFMC is recoverable/retryable.
        """
        token_url = f"https://{self.token_host}/v2/token"
        token_data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        token_headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                token_url, headers=token_headers, json=token_data, timeout=30
            )

            if response.status_code == 200:
                return response.json()["access_token"]

            error_msg = (
                f"SFMC token request failed with status {response.status_code}: "
                f"{response.reason}"
            )

            # Retry on rate limiting or server errors
            if response.status_code == 429 or 500 <= response.status_code < 600:
                logger.warning(error_msg)
                raise SalesforceMarketingCloudRecoverableException(error_msg)
            else:
                logger.error(error_msg)
                raise SalesforceMarketingCloudException(error_msg)

        except requests.exceptions.RequestException as exc:
            error_msg = f"SFMC token request failed with exception: {str(exc)}"
            logger.error(error_msg)
            raise SalesforceMarketingCloudRecoverableException(error_msg)

    @backoff.on_exception(
        backoff.expo,
        SalesforceMarketingCloudRecoverableException,
        max_tries=MAX_ATTEMPTS,
    )
    def delete_user(self, user: dict) -> None:
        """
        Delete a user from Salesforce Marketing Cloud by marking them for deletion.

        This method sends a request to SFMC to add the user's subscriber key to the
        deletion data extension, marking them for removal.

        Args:
            user (dict): User data containing 'user' key with 'id' field (LMS user ID)

        Raises:
            TypeError: if user ID is not provided
            SalesforceMarketingCloudException: if the error from SFMC is unrecoverable/unretryable.
            SalesforceMarketingCloudRecoverableException: if the error from SFMC is recoverable/retryable.
        """
        # Extract user ID from the learner dict
        user_id = None
        if isinstance(user, dict):
            user_data = user.get("user", {})
            if isinstance(user_data, dict):
                user_id = user_data.get("id")
            else:
                user_id = user_data

        if not user_id:
            raise TypeError(
                "Expected a user ID for user to delete, but received None."
            )

        # Convert user_id to string for the API
        subscriber_key = str(user_id)

        # Get access token
        access_token = self._get_access_token()

        # Prepare deletion request
        suppression_route = "hub/v1/dataevents/key:Contacts_for_Delete/rowset"
        suppress_url = f"https://{self.suppression_host}/{suppression_route}"
        suppress_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        suppress_data = [
            {
                "keys": {"Subscriberkey": subscriber_key},
                "values": {"IsDelete": "True"},
            }
        ]

        try:
            response = requests.post(
                suppress_url,
                headers=suppress_headers,
                json=suppress_data,
                timeout=30,
            )

            if response.status_code == 200:
                logger.info(
                    f"SFMC user deletion succeeded for subscriber key: {subscriber_key}"
                )
                return

            # Parse error response
            error_msg = (
                f"SFMC user deletion failed with status {response.status_code}: "
                f"{response.reason}"
            )

            try:
                error_details = response.json()
                if error_details:
                    error_msg += f" - Details: {error_details}"
            except ValueError:
                # Response is not JSON
                pass

            # Retry on rate limiting or server errors
            if response.status_code == 429 or 500 <= response.status_code < 600:
                logger.warning(error_msg)
                raise SalesforceMarketingCloudRecoverableException(error_msg)
            else:
                logger.error(error_msg)
                raise SalesforceMarketingCloudException(error_msg)

        except requests.exceptions.RequestException as exc:
            error_msg = (
                f"SFMC user deletion failed with exception for subscriber key "
                f"{subscriber_key}: {str(exc)}"
            )
            logger.error(error_msg)
            raise SalesforceMarketingCloudRecoverableException(error_msg)
