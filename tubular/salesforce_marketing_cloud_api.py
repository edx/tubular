"""
Salesforce Marketing Cloud API class that is used to delete a user from SFMC.
"""

import logging
import os
from typing import Optional

import backoff
import requests

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = int(os.environ.get("RETRY_SFMC_MAX_ATTEMPTS", 5))


class SalesforceMarketingCloudException(Exception):
    """
    SalesforceMarketingCloudException will be raised when a fatal, non-recoverable error occurs.
    """

    pass


class SalesforceMarketingCloudRecoverableException(SalesforceMarketingCloudException):
    """
    SalesforceMarketingCloudRecoverableException will be raised when the request can be retried.
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
    ):
        """
        Initialize the SFMC API client.

        Args:
            client_id: SFMC OAuth client ID
            client_secret: SFMC OAuth client secret
            subdomain: SFMC subdomain (e.g., 'mc123456789')
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.subdomain = subdomain
        self.token_host = f"{subdomain}.auth.marketingcloudapis.com"
        self.suppression_host = f"{subdomain}.rest.marketingcloudapis.com"

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
    def _get_contact_key_by_email(self, email: str, access_token: str) -> Optional[str]:
        """
        Search for a contact in SFMC by email and retrieve their contact key.

        Args:
            email (str): Email address to search for
            access_token (str): SFMC OAuth access token

        Returns:
            str: Contact key if found, None otherwise

        Raises:
            SalesforceMarketingCloudException: if the error from SFMC is unrecoverable/unretryable.
            SalesforceMarketingCloudRecoverableException: if the error from SFMC is recoverable/retryable.
        """
        search_route = "contacts/v1/addresses/email/search"
        search_url = f"https://{self.suppression_host}/{search_route}"
        search_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        search_data = {
            "ChannelAddressList": [email],
            "MaximumCount": 5
        }

        try:
            response = requests.post(
                search_url,
                headers=search_headers,
                json=search_data,
                timeout=30,
            )

            if response.status_code == 200:
                response_data = response.json()
                channel_address_entities = response_data.get('channelAddressResponseEntities', [])
                
                if not channel_address_entities:
                    logger.info(f"SFMC contact search found no contact for email: {email}")
                    return None
                
                contact_key_details = channel_address_entities[0].get('contactKeyDetails', [])
                if not contact_key_details:
                    logger.info(f"SFMC contact search found no contact for email: {email}")
                    return None
                
                contact_key = contact_key_details[0].get('contactKey')
                logger.info(
                    f"SFMC contact search succeeded for email {email}, found contact key: {contact_key}"
                )
                return contact_key

            error_msg = (
                f"SFMC contact search failed with status {response.status_code}: "
                f"{response.reason}"
            )

            try:
                error_details = response.json()
                if error_details:
                    error_msg += f" - Details: {error_details}"
            except ValueError:
                # Response body is not valid JSON, skip adding error details
                pass

            if response.status_code == 429 or 500 <= response.status_code < 600:
                logger.warning(error_msg)
                raise SalesforceMarketingCloudRecoverableException(error_msg)
            else:
                logger.error(error_msg)
                raise SalesforceMarketingCloudException(error_msg)

        except requests.exceptions.RequestException as exc:
            error_msg = (
                f"SFMC contact search failed with exception for email "
                f"{email}: {str(exc)}"
            )
            logger.error(error_msg)
            raise SalesforceMarketingCloudRecoverableException(error_msg)

    @backoff.on_exception(
        backoff.expo,
        SalesforceMarketingCloudRecoverableException,
        max_tries=MAX_ATTEMPTS,
    )
    def delete_user(self, user: dict) -> None:
        """
        Delete a user from Salesforce Marketing Cloud.

        This method first searches for the user by email to get their contact key,
        then uses that contact key to delete the contact from SFMC.

        Args:
            user (dict): User data containing 'original_email' field

        Raises:
            TypeError: if user email is not provided
            SalesforceMarketingCloudException: if the error from SFMC is unrecoverable/unretryable.
            SalesforceMarketingCloudRecoverableException: if the error from SFMC is recoverable/retryable.
        """
        email = user.get('original_email')
        if not email:
            raise TypeError("User email is required for SFMC deletion")

        access_token = self._get_access_token()

        contact_key = self._get_contact_key_by_email(email, access_token)
        
        if not contact_key:
            logger.info(f"No contact found in SFMC for email {email}, nothing to delete")
            return

        delete_route = "contacts/v1/contacts/actions/delete?type=keys"
        delete_url = f"https://{self.suppression_host}/{delete_route}"
        delete_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        delete_data = {
            "values": [contact_key],
            "DeleteOperationType": "ContactAndAttributes"
        }

        try:
            response = requests.post(
                delete_url,
                headers=delete_headers,
                json=delete_data,
                timeout=30,
            )

            if response.status_code == 200:
                logger.info(
                    f"SFMC user deletion succeeded for contact key: {contact_key}"
                )
                return

            error_msg = (
                f"SFMC user deletion failed with status {response.status_code}: "
                f"{response.reason}"
            )

            try:
                error_details = response.json()
                if error_details:
                    error_msg += f" - Details: {error_details}"
            except ValueError:
                pass

            if response.status_code == 429 or 500 <= response.status_code < 600:
                logger.warning(error_msg)
                raise SalesforceMarketingCloudRecoverableException(error_msg)
            else:
                logger.error(error_msg)
                raise SalesforceMarketingCloudException(error_msg)

        except requests.exceptions.RequestException as exc:
            error_msg = (
                f"SFMC user deletion failed with exception for "
                f"contact key {contact_key}: {str(exc)}"
            )
            logger.error(error_msg)
            raise SalesforceMarketingCloudRecoverableException(error_msg)
