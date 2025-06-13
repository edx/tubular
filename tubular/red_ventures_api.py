"""
RedVentures API class that is used to delete user from Red Ventures.
"""

import logging
import requests
import backoff
import os

from auth0.authentication import GetToken

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = int(os.environ.get("RETRY_MAX_ATTEMPTS", 5))


class RedVenturesException(Exception):
    """
    RedVenturesException will be raised there is fatal error and is not recoverable.
    """

    pass


class RedVenturesRecoverableException(RedVenturesException):
    """
    RedVenturesRecoverableException will be raised when request can be retryable.
    """

    pass


class RedVenturesApi:
    """
    RedVentures API is used to handle communication with RedVentures APIs.
    """

    def __init__(
        self,
        red_ventures_audience: str,
        red_ventures_auth_url: str,
        red_ventures_deletion_url: str,
        red_ventures_username: str,
        red_ventures_password: str,
    ):
        self.audience = red_ventures_audience
        self.auth_url = red_ventures_auth_url
        self.deletion_url = red_ventures_deletion_url
        self.username = red_ventures_username
        self.password = red_ventures_password

    def get_token(self):
        token = GetToken(self.auth_url, self.username, client_secret=self.password)
        return token.client_credentials(self.audience)

    @backoff.on_exception(
        backoff.expo,
        RedVenturesRecoverableException,
        max_tries=MAX_ATTEMPTS,
    )
    def delete_user(self, user: dict) -> None:
        """
        This function sends an API request to delete a user from Red Ventures. It then parses the response and
        try again if it is recoverable.

        Returns:
            None

        Args:
            user (dict): raw data of user to delete.

        Raises:
          RedVenturesException: if the error from Red Ventures is unrecoverable/unretryable.
          RedVenturesRecoverableException: if the error from Red Ventures is recoverable/retryable.
        """

        auth_token = self.get_token()["access_token"]
        headers = {
            "Authorization": "Bearer {}".format(auth_token),
            "Content-Type": "application/json",
        }

        email = user.get("original_email", None)
        if not email:
            raise TypeError(
                "Expected an email address for user to delete, but received None."
            )
        response = requests.delete(
            self.deletion_url, params={"email": email}, headers=headers
        )

        if response.status_code == 204:
            logger.info("Red Ventures user deletion succeeded")
            return

        # We have some sort of error. Parse it, log it, and retry as needed.
        error_msg = (
            "Red Ventures user deletion failed with {status} due to {reason}".format(
                status=response.status_code,
                reason=response.reason,
            )
        )
        logger.error(error_msg)
        # 5xx errors might be temporary,  if something strange is happening on the server side.
        if 500 <= response.status_code < 600:
            raise RedVenturesRecoverableException(error_msg)
        else:
            raise RedVenturesException(error_msg)
