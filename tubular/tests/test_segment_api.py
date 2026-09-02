"""
Tests for the Segment API functionality
"""
import json
import mock
import pytest

import requests
from six import text_type

from tubular.segment_api import SegmentApi, BULK_REGULATE_URL
from tubular.tests.retirement_helpers import get_fake_user_retirement

FAKE_AUTH_TOKEN = 'FakeToken'
TEST_SEGMENT_CONFIG = {
    'projects_to_retire': ['project_1', 'project_2'],
    'learner': [get_fake_user_retirement(), ],
    'fake_base_url': 'https://segment.invalid/',
    'fake_auth_token': FAKE_AUTH_TOKEN,
    'fake_workspace': 'FakeEdx',
    'headers': {"Authorization": "Bearer {}".format(FAKE_AUTH_TOKEN), "Content-Type": "application/json"}
}


class FakeResponse:
    """
    Fakes out requests.post response
    """
    def json(self):
        """
        Returns fake Segment retirement response data in the correct format
        """
        return {'regulate_id': 1}

    def raise_for_status(self):
        pass


class FakeErrorResponse:
    """
    Fakes an error response
    """
    status_code = 500
    text = '{"error": "Test error message"}'
    headers = {}

    def json(self):
        """
        Returns fake Segment retirement response error in the correct format
        """
        return json.loads(self.text)

    def raise_for_status(self):
        raise requests.exceptions.HTTPError("", response=self)


class FakeRateLimitedResponse:
    """
    Fakes a 429 rate-limited response that includes a Retry-After header, as Segment does.
    """
    status_code = 429
    text = '{"error": "Rate limited"}'
    headers = {'Retry-After': '1'}

    def json(self):
        """
        Returns fake Segment retirement response error in the correct format
        """
        return json.loads(self.text)

    def raise_for_status(self):
        raise requests.exceptions.HTTPError("", response=self)


@pytest.fixture
def setup_regulation_api():
    """
    Fixture to setup common bulk delete items.
    """
    with mock.patch('requests.post') as mock_post:
        segment = SegmentApi(
            *[TEST_SEGMENT_CONFIG[key] for key in [
                'fake_base_url', 'fake_auth_token', 'fake_workspace'
            ]]
        )

        yield mock_post, segment


def test_bulk_delete_success(setup_regulation_api):  # pylint: disable=redefined-outer-name
    """
    Test simple success case
    """
    mock_post, segment = setup_regulation_api
    mock_post.return_value = FakeResponse()

    learner = TEST_SEGMENT_CONFIG['learner']
    segment.delete_and_suppress_learners(learner, 1000)

    assert mock_post.call_count == 1

    expected_learner = get_fake_user_retirement()
    learners_vals = [
        text_type(expected_learner['user']['id']),
        expected_learner['original_username'],
        expected_learner['ecommerce_segment_id'],
    ]

    fake_json = {
        "regulation_type": "Suppress_With_Delete",
        "attributes": {
            "name": "userId",
            "values": learners_vals
        }
    }

    url = TEST_SEGMENT_CONFIG['fake_base_url'] + BULK_REGULATE_URL.format(TEST_SEGMENT_CONFIG['fake_workspace'])
    mock_post.assert_any_call(
        url, json=fake_json, headers=TEST_SEGMENT_CONFIG['headers']
    )


def test_bulk_delete_error(setup_regulation_api, caplog):  # pylint: disable=redefined-outer-name
    """
    Test simple error case
    """
    mock_post, segment = setup_regulation_api
    mock_post.return_value = FakeErrorResponse()

    learner = TEST_SEGMENT_CONFIG['learner']
    with mock.patch('time.sleep'):
        with pytest.raises(Exception):
            segment.delete_and_suppress_learners(learner, 1000)

    assert mock_post.call_count == 4
    assert "Error was encountered for params:" in caplog.text
    assert "9009" in caplog.text
    assert "foo_username" in caplog.text
    assert "ecommerce-90" in caplog.text
    assert "Suppress_With_Delete" in caplog.text
    assert "Test error message" in caplog.text


def test_bulk_delete_429_respects_retry_after(setup_regulation_api):  # pylint: disable=redefined-outer-name
    """
    A 429 from Segment should be retried, waiting for exactly the duration given by the
    Retry-After header on each attempt rather than jumping straight to computed backoff.
    """
    mock_post, segment = setup_regulation_api
    mock_post.return_value = FakeRateLimitedResponse()

    learner = TEST_SEGMENT_CONFIG['learner']
    with mock.patch('time.sleep') as mock_sleep:
        with pytest.raises(Exception):
            segment.delete_and_suppress_learners(learner, 1000)

    # All 4 tries are attempted (429 is retryable) before giving up.
    assert mock_post.call_count == 4

    # 3 waits happen between the 4 tries, each honoring the 1 second Retry-After header
    # instead of the exponential 1/2/4 second schedule used when no header is present.
    assert mock_sleep.call_count == 3
    for call in mock_sleep.call_args_list:
        assert call.args[0] == 1.0


def test_bulk_delete_500_falls_back_to_default_wait(setup_regulation_api):  # pylint: disable=redefined-outer-name
    """
    A plain 5xx with no Retry-After header should fall back to a wait that grows by
    the fixed 30 second increment used elsewhere in this module on each successive
    try, rather than trying to honor a missing header.
    """
    mock_post, segment = setup_regulation_api
    mock_post.return_value = FakeErrorResponse()

    learner = TEST_SEGMENT_CONFIG['learner']
    with mock.patch('time.sleep') as mock_sleep:
        with pytest.raises(Exception):
            segment.delete_and_suppress_learners(learner, 1000)

    assert mock_post.call_count == 4
    assert [call.args[0] for call in mock_sleep.call_args_list] == [30, 60, 90]


def test_bulk_unsuppress_success(setup_regulation_api):  # pylint: disable=redefined-outer-name
    """
    Test simple success case
    """
    mock_post, segment = setup_regulation_api
    mock_post.return_value = FakeResponse()

    learner = TEST_SEGMENT_CONFIG['learner']
    segment.unsuppress_learners_by_key('original_username', learner, 100)

    assert mock_post.call_count == 1

    expected_learner = get_fake_user_retirement()

    fake_json = {
        "regulation_type": "Unsuppress",
        "attributes": {
            "name": "userId",
            "values": [expected_learner['original_username'], ]
        }
    }

    url = TEST_SEGMENT_CONFIG['fake_base_url'] + BULK_REGULATE_URL.format(TEST_SEGMENT_CONFIG['fake_workspace'])
    mock_post.assert_any_call(
        url, json=fake_json, headers=TEST_SEGMENT_CONFIG['headers']
    )


def test_bulk_unsuppress_error(setup_regulation_api, caplog):  # pylint: disable=redefined-outer-name
    """
    Test simple error case
    """
    mock_post, segment = setup_regulation_api
    mock_post.return_value = FakeErrorResponse()

    learner = TEST_SEGMENT_CONFIG['learner']
    with mock.patch('time.sleep'):
        with pytest.raises(Exception):
            segment.unsuppress_learners_by_key('original_username', learner, 100)

    assert mock_post.call_count == 4
    assert "Error was encountered for params:" in caplog.text
    assert "9009" not in caplog.text
    assert "foo_username" in caplog.text
    assert "ecommerce-90" not in caplog.text
    assert "Unsuppress" in caplog.text
    assert "Test error message" in caplog.text
