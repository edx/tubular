"""
Tests for tubular.github_api.GitHubAPI
"""

from datetime import datetime, date
from hashlib import sha1

from unittest import TestCase
import ddt
from mock import patch, Mock

from github import GithubException, Github
from github import UnknownObjectException
from github.Branch import Branch
from github.Commit import Commit
from github.Comparison import Comparison
from github.CommitStatus import CommitStatus
from github.CommitCombinedStatus import CommitCombinedStatus
from github.GitCommit import GitCommit
from github.GitRef import GitRef
from github.Issue import Issue
from github.IssueComment import IssueComment
from github.NamedUser import NamedUser
from github.Organization import Organization
from github.PullRequest import PullRequest
from github.Repository import Repository

import six
from tubular import github_api
from tubular.exception import InvalidUrlException
from tubular.github_api import (
    GitHubAPI,
    InvalidPullRequestError,
    GitTagMismatchError,
)

# SHA1 is hash function designed to be difficult to reverse.
# This dictionary will help us map SHAs back to the hashed values.
SHA_MAP = {sha1(six.text_type(i).encode('utf-8')).hexdigest(): i for i in range(37)}
# These will be used as test data to feed test methods below which
# require SHAs.
SHAS = sorted(SHA_MAP.keys())
# This dictionary is used to convert trimmed SHAs back into the
# originally hashed values.
TRIMMED_SHA_MAP = {sha[:10]: i for sha, i in SHA_MAP.items()}


@ddt.ddt
class GitHubApiTestCase(TestCase):
    """
    Tests the requests creation/response handling for the Github API
    All Network calls should be mocked out.
    """

    def setUp(self):
        with patch.object(Github, 'get_organization', return_value=Mock(spec=Organization)) as org_mock:
            with patch.object(Github, 'get_repo', return_value=Mock(spec=Repository)) as repo_mock:
                self.org_mock = org_mock.return_value = Mock(spec=Organization)
                self.repo_mock = repo_mock.return_value = Mock(spec=Repository)
                self.api = GitHubAPI('test-org', 'test-repo', token='abc123')
        self.api.log_rate_limit = Mock(return_value=None)
        self.api.get_branch_protection_rules = Mock(return_value=[])
        super(GitHubApiTestCase, self).setUp()

    @patch('github.Github.get_user')
    def test_user(self, mock_user_method):
        # setup the mock
        mock_user_method.return_value = Mock(spec=NamedUser)

        self.assertIsInstance(self.api.user(), NamedUser)
        mock_user_method.assert_called()

    @ddt.data(
        ('abc', 'success'),
        ('123', 'failure'),
        (Mock(spec=GitCommit, **{'sha': '123'}), 'success'),
        (Mock(spec=GitCommit, **{'sha': '123'}), 'failure')
    )
    @ddt.unpack
    def test_get_commit_combined_statuses(self, sha, state):
        combined_status = Mock(spec=CommitCombinedStatus, state=state)
        attrs = {'get_combined_status.return_value': combined_status}
        commit_mock = Mock(spec=Commit, **attrs)
        self.repo_mock.get_commit = lambda sha: commit_mock

        status = self.api.get_commit_combined_statuses(sha)
        self.assertEqual(status.state, state)

    def test_get_commit_combined_statuses_passing_commit_obj(self):
        combined_status = Mock(spec=CommitCombinedStatus, **{'state': 'success'})
        attrs = {'get_combined_status.return_value': combined_status}
        commit_mock = Mock(spec=Commit, **attrs)
        self.repo_mock.get_commit = lambda sha: commit_mock

        status = self.api.get_commit_combined_statuses(commit_mock)
        self.assertEqual(status.state, 'success')

    def test_get_commit_combined_statuses_bad_object(self):
        self.assertRaises(UnknownObjectException, self.api.get_commit_combined_statuses, object())

    def test_get_commits_by_branch(self):
        self.repo_mock.get_branch.return_value = Mock(spec=Branch, **{'commit.sha': '123'})
        self.repo_mock.get_commits.return_value = [Mock(spec=Commit, sha=i) for i in range(10)]

        commits = self.api.get_commits_by_branch('test')

        self.repo_mock.get_branch.assert_called_with('test')
        self.repo_mock.get_commits.assert_called_with('123')
        self.assertEqual(len(commits), 10)

    def test_get_diff_url(self):
        def _check_url(org, repo, base_sha, head_sha):
            """ private method to do the comparison of the expected URL and the one we get back """
            url = self.api.get_diff_url(org, repo, base_sha, head_sha)
            expected = 'https://github.com/{}/{}/compare/{}...{}'.format(org, repo, base_sha, head_sha)
            self.assertEqual(url, expected)

        _check_url('org', 'repo', 'base-sha', 'head-sha')
        with self.assertRaises(InvalidUrlException):
            _check_url('org', 'repo', 'abc def', 'head-sha')

    def test_get_commits_by_branch_branch_not_found(self):
        self.repo_mock.get_branch.side_effect = GithubException(
            404,
            {
                'documentation_url': 'https://developer.github.com/v3/repos/#get-branch',
                'message': 'Branch not found'
            },
            headers={}
        )
        self.assertRaises(GithubException, self.api.get_commits_by_branch, 'blah')

    def test_delete_branch(self):
        ref_mock = Mock(spec=GitRef)
        get_git_ref_mock = Mock(return_value=ref_mock)
        self.repo_mock.get_git_ref = get_git_ref_mock
        self.api.delete_branch('blah')

        get_git_ref_mock.assert_called_with(ref='heads/blah')
        ref_mock.delete.assert_called()

    @ddt.data(
        ('blah-candidate', 'release', 'test', 'test_pr'),
        ('catnip', 'release', 'My meowsome PR', 'this PR has lots of catnip inside, go crazy!'),
    )
    @ddt.unpack
    def test_create_pull_request(self, head, base, title, body):
        self.api.create_pull_request(
            head=head,
            base=base,
            title=title,
            body=body
        )
        self.repo_mock.create_pull.assert_called_with(
            head=head,
            base=base,
            title=title,
            body=body
        )

    @ddt.data('test.user@edx.org', None)
    def test_create_tag(self, user_email):
        mock_user = Mock(spec=NamedUser)
        mock_user.email = user_email
        mock_user.name = 'test_name'
        with patch.object(Github, 'get_user', return_value=mock_user):
            create_tag_mock = Mock()
            create_ref_mock = Mock()
            self.repo_mock.create_git_tag = create_tag_mock
            self.repo_mock.create_git_ref = create_ref_mock

            test_tag = 'test_tag'
            test_sha = 'abc'
            self.api.create_tag(test_sha, test_tag)
            _, kwargs = create_tag_mock.call_args  # pylint: disable=unpacking-non-sequence
            self.assertEqual(kwargs['tag'], test_tag)
            self.assertEqual(kwargs['message'], '')
            self.assertEqual(kwargs['type'], 'commit')
            self.assertEqual(kwargs['object'], test_sha)
            create_ref_mock.assert_called_with(
                ref='refs/tags/{}'.format(test_tag),
                sha=test_sha
            )

    def _setup_create_tag_mocks(self, status_code, msg, return_sha):
        """
        Setup the mocks for the create_tag calls below.
        """
        mock_user = Mock(NamedUser, email='test.user@edx.org')
        mock_user.name = 'test_name'
        self.repo_mock.create_git_tag = Mock()
        self.repo_mock.create_git_ref = Mock(
            side_effect=GithubException(status_code, {'message': msg}, {})
        )
        self.repo_mock.get_git_ref = get_tag_mock = Mock()
        get_tag_mock.return_value = Mock(object=Mock(sha=return_sha))
        return mock_user

    def test_create_tag_which_already_exists_but_matches_sha(self):
        test_sha = 'abc'
        mock_user = self._setup_create_tag_mocks(
            422, 'Reference already exists', test_sha
        )
        with patch.object(Github, 'get_user', return_value=mock_user):
            # No exception.
            self.api.create_tag(test_sha, 'test_tag')

    def test_create_tag_which_already_exists_and_no_sha_match(self):
        mock_user = self._setup_create_tag_mocks(
            422, 'Reference already exists', 'def'
        )
        with patch.object(Github, 'get_user', return_value=mock_user):
            with self.assertRaises(GitTagMismatchError):
                self.api.create_tag('abc', 'test_tag')

    def test_create_tag_which_already_exists_and_unknown_exception(self):
        mock_user = self._setup_create_tag_mocks(
            421, 'Not sure what this is!', 'def'
        )
        with patch.object(Github, 'get_user', return_value=mock_user):
            with self.assertRaises(GithubException):
                self.api.create_tag('abc', 'test_tag')

    @ddt.data(
        ('123', list(range(10)), 10, 'SuCcEsS', True, True, False),
        ('123', list(range(10)), 10, 'success', True, True, False),
        ('123', list(range(10)), 10, 'SUCCESS', True, True, False),
        ('123', list(range(10)), 10, 'pending', False, True, False),
        ('123', list(range(10)), 10, 'failure', False, True, False),
        ('123', [], 0, None, False, True, False),
        ('123', list(range(10)), 8, 'SuCcEsS', True, False, False),
        ('123', list(range(10)), 8, 'success', True, False, False),
        ('123', list(range(10)), 10, 'success', True, False, True),
        ('123', list(range(10)), 8, 'SUCCESS', True, False, False),
        ('123', list(range(10)), 8, 'pending', False, False, False),
        ('123', list(range(10)), 10, 'pending', False, False, True),
        ('123', list(range(10)), 8, 'failure', False, False, False),
        ('123', [], 0, None, False, False, False)
    )
    @ddt.unpack
    def test_check_combined_status_commit(
            self, sha, statuses, statuses_returned, state, success_expected, use_statuses, all_checks
    ):
        if use_statuses:
            mock_combined_status = Mock(spec=CommitCombinedStatus)
            mock_combined_status.statuses = [Mock(spec=CommitStatus, id=i, state=state) for i in statuses]
            mock_combined_status.state = state

            commit_mock = Mock(spec=Commit, url="some.fake.repo/")
            commit_mock.get_combined_status.return_value = mock_combined_status
            self.repo_mock.get_commit.return_value = commit_mock

            commit_mock._requester = Mock()  # pylint: disable=protected-access
            # pylint: disable=protected-access
            commit_mock._requester.requestJsonAndCheck.return_value = (
                {}, {'check_suites': [], 'check_runs': []})
        else:
            mock_combined_status = Mock(spec=CommitCombinedStatus)
            mock_combined_status.statuses = []
            mock_combined_status.state = None
            mock_combined_status.url = None

            commit_mock = Mock(spec=Commit, url="some.fake.repo/")
            commit_mock.get_combined_status.return_value = mock_combined_status
            self.repo_mock.get_commit.return_value = commit_mock

            self.api.get_branch_protection_rules = Mock(return_value=['App {}'.format(i) for i in statuses][:8])

            commit_mock._requester = Mock()  # pylint: disable=protected-access
            # pylint: disable=protected-access
            commit_mock._requester.requestJsonAndCheck.return_value = (
                {},
                {
                    'check_suites': [
                        {
                            'app': {
                                'name': 'App {}'.format(i)
                            },
                            'conclusion': state,
                            'url': 'some.fake.repo'
                        } for i in statuses
                    ],
                    'check_runs': [
                        {
                            'name': 'App {}'.format(i),
                            'app': {
                                'name': 'App {}'.format(i)
                            },
                            'conclusion': state,
                            'url': 'some.fake.repo'
                        } for i in statuses
                    ]
                },
            )

        self.api.all_checks = all_checks
        successful, statuses = self.api.check_combined_status_commit(sha)

        assert successful == success_expected
        assert isinstance(statuses, dict)
        assert len(statuses) == statuses_returned
        commit_mock.get_combined_status.assert_called()
        self.repo_mock.get_commit.assert_called_with(sha)

    @ddt.data(
        ('', 'success', None),  # Case where no actions are found
        ('passed', 'passed', True),    # Case where actions are found and succeed
        ('failed', 'failed', False),   # Case where actions are found and fail
    )
    @ddt.unpack
    def test_poll_commit(self, initial_status, end_status, successful):
        url_dict = {'TravisCI': 'some url'}
        side_effects = [
            (False, url_dict, initial_status) if initial_status == '' else (True, url_dict, initial_status),
            (successful, url_dict, end_status),
        ]
        
        with patch.object(self.api, '_is_commit_successful', side_effect=side_effects) as mock_is_commit_successful:
            result = self.api._poll_commit('some sha')  # pylint: disable=protected-access

            if initial_status == '':
                # We expect the function to return immediately after the first call
                assert result[0] == 'success'
                assert result[1] is None
            else:
                # Ensure the function processes both calls
                assert result[0] == end_status
                assert result[1] == url_dict

    @ddt.data(
        (
            None,
            None,
            [
                '{}-{}'.format(state, valtype)
                for state in ['passed', 'pending', None, 'failed']
                for valtype in ['status', 'check']
            ] + ['python-unit-tests']
        ),
        ('status', None, ['passed-check', 'pending-check', 'None-check', 'failed-check', 'python-unit-tests']),
        ('check', None, ['passed-status', 'pending-status', 'None-status', 'failed-status', 'python-unit-tests']),
        ('check', 'passed', ['passed-status', 'passed-check', 'pending-status', 'None-status', 'failed-status', 'python-unit-tests']),
        ('.*', 'passed', ['passed-status', 'passed-check']),
    )
    @ddt.unpack
    def test_filter_validation(self, exclude_contexts, include_contexts, expected_contexts):
        filterable_states = ['passed', 'pending', None, 'failed']

        with patch.object(
                Github,
                'get_organization',
                return_value=Mock(name='org-mock', spec=Organization)
        ):
            with patch.object(Github, 'get_repo', return_value=Mock(name='repo-mock', spec=Repository)) as repo_mock:
                api = GitHubAPI(
                    'test-org',
                    'test-repo',
                    token='abc123',
                    exclude_contexts=exclude_contexts,
                    include_contexts=include_contexts
                )
        api.log_rate_limit = Mock(return_value=None)
        api.get_branch_protection_rules = Mock(
            return_value=[
                'passed-check', 'pending-check', 'python-unit-tests',
                'None-check', 'python-unit-tests', 'failed-check']
        )

        mock_combined_status = Mock(name='combined-status', spec=CommitCombinedStatus)
        mock_combined_status.statuses = [
            Mock(name='{}-status'.format(state), spec=CommitStatus, context='{}-status'.format(state), state=state)
            for state in filterable_states
        ]
        mock_combined_status.state = None
        mock_combined_status.url = None

        commit_mock = Mock(name='commit', spec=Commit, url="some.fake.repo/")
        commit_mock.get_combined_status.return_value = mock_combined_status
        repo_mock.return_value.get_commit.return_value = commit_mock
        commit_mock._requester = Mock(name='_requester')  # pylint: disable=protected-access
        # pylint: disable=protected-access
        commit_mock._requester.requestJsonAndCheck.return_value = (
            {},
            {
                'check_suites': [
                    {
                        'app': {
                            'name': '{}-check'.format(state)
                        },
                        'conclusion': state,
                        'url': 'some.fake.repo'
                    } for state in filterable_states
                ],
                'check_runs': [
                    {
                        'name': 'python-unit-tests',
                        'app': {
                            'name': '{}-check'.format(state)
                        },
                        'conclusion': state,
                        'url': 'some.fake.repo'
                    } for state in filterable_states
                ]
            }
        )
        filtered_results = api.filter_validation_results(api.get_validation_results('deadbeef'))
        assert set(expected_contexts) == set(filtered_results.keys())

    @ddt.data(
        # 1 unique SHA should result in 1 search query and 1 PR.
        (SHAS[:1], 1, 1),
        # 18 unique SHAs should result in 1 search query and 18 PRs.
        (SHAS[:18], 1, 18),
        # 36 unique SHAs should result in 2 search queries and 36 PRs.
        (SHAS[:36], 2, 36),
        # 37 unique SHAs should result in 3 search queries and 37 PRs.
        (SHAS[:37], 3, 37),
        # 20 unique SHAs, each appearing twice, should result in 3 search queries and 20 PRs.
        (SHAS[:20] * 2, 3, 20),
    )
    @ddt.unpack
    @patch('github.Github.search_issues')
    def test_get_pr_range(self, shas, expected_search_count, expected_pull_count, mock_search_issues):
        commits = [Mock(spec=Commit, sha=sha) for sha in shas]
        self.repo_mock.compare.return_value = Mock(spec=Comparison, commits=commits)

        def search_issues_side_effect(query, **kwargs):  # pylint: disable=unused-argument
            """
            Stub implementation of GitHub issue search.
            """
            return [Mock(
                spec=Issue,
                number=TRIMMED_SHA_MAP[query_item],
                repository=self.repo_mock,
            ) for query_item in query.split() if query_item in TRIMMED_SHA_MAP]
            # The query is all the shas + params to narry the query to PRs and repo.
            # This shouldn't break the intent of the test because we are still pulling
            # in all the params that are relevant to this test which are the passed in
            # shas.  And it's ignoring other parameters that search_issues might add
            # to the test.

        mock_search_issues.side_effect = search_issues_side_effect

        self.repo_mock.get_pull = lambda number: Mock(spec=PullRequest, number=number)

        start_sha, end_sha = 'abc', '123'
        pulls = self.api.get_pr_range(start_sha, end_sha)

        self.repo_mock.compare.assert_called_with(start_sha, end_sha)

        self.assertEqual(mock_search_issues.call_count, expected_search_count)
        for call_args in mock_search_issues.call_args_list:
            # Verify that the batched SHAs have been trimmed.
            self.assertLess(len(call_args[0]), 200)

        self.assertEqual(len(pulls), expected_pull_count)
        for pull in pulls:
            self.assertIsInstance(pull, PullRequest)

    @ddt.data(
        ('Deployed to PROD', [':+1:', ':+1:', ':ship: :it:'], True, IssueComment),
        ('Deployed to stage', ['wahoo', 'want BLT', 'Deployed, to PROD'], False, IssueComment),
        ('Deployed to PROD', [':+1:', 'law school man', '@macdiesel Deployed to PROD'], True, IssueComment),
        ('Deployed to stage', [':+1:', ':+1:', '@macdiesel dEpLoYeD tO stage'], False, None),
        ('Deployed to stage', ['@macdiesel dEpLoYeD tO stage', ':+1:', ':+1:'], False, IssueComment),
        ('Deployed to PROD', [':+1:', ':+1:', '@macdiesel Deployed to PROD'], False, None),
    )
    @ddt.unpack
    def test_message_pull_request(self, new_message, existing_messages, force_message, expected_result):
        comments = [Mock(spec=IssueComment, body=message) for message in existing_messages]
        self.repo_mock.get_pull.return_value = \
            Mock(spec=PullRequest,
                 get_issue_comments=Mock(return_value=comments),
                 create_issue_comment=lambda message: Mock(spec=IssueComment, body=message))

        result = self.api.message_pull_request(1, new_message, new_message, force_message)

        self.repo_mock.get_pull.assert_called()
        if expected_result:
            self.assertIsInstance(result, IssueComment)
            self.assertEqual(result.body, new_message)
        else:
            self.assertEqual(result, expected_result)

    def test_message_pr_does_not_exist(self):
        with patch.object(self.repo_mock, 'get_pull', side_effect=UnknownObjectException(404, '', {})):
            self.assertRaises(InvalidPullRequestError, self.api.message_pull_request, 3, 'test', 'test')

    @ddt.data(
        (datetime(2017, 1, 9, 11), date(2017, 1, 10)),
        (datetime(2017, 1, 13, 11), date(2017, 1, 16)),
    )
    @ddt.unpack
    def test_message_pr_deployed_stage_weekend(self, message_date, deploy_date):
        with patch.object(self.api, 'message_pull_request') as mock:
            with patch.object(github_api, 'datetime', Mock(wraps=datetime)) as mock_datetime:
                mock_datetime.now.return_value = message_date
                self.api.message_pr_with_type(1, github_api.MessageType.stage, deploy_date=deploy_date)

                mock.assert_called_with(
                    1,
                    github_api.PR_MESSAGE_FORMAT.format(
                        prefix=github_api.PR_PREFIX,
                        message=github_api.MessageType.stage.value,
                        extra_text=github_api.PR_ON_STAGE_DATE_EXTRA.format(date=deploy_date, extra_text='')
                    ),
                    github_api.PR_MESSAGE_FORMAT.format(
                        prefix=github_api.PR_PREFIX,
                        message=github_api.MessageType.stage.value,
                        extra_text=github_api.PR_ON_STAGE_DATE_EXTRA.format(date=deploy_date, extra_text='')
                    ),
                    False
                )

    @ddt.data(
        (1, github_api.MessageType.prod, '', False),
        (1337, github_api.MessageType.prod, 'some extra words', False),
        (867, github_api.MessageType.prod_rollback, '', True),
        (5, github_api.MessageType.prod_rollback, 'Elmo does not approve', False),
    )
    @ddt.unpack
    def test_message_pr_methods(self, pr_number, message_type, extra_text, force_message):
        with patch.object(self.api, 'message_pull_request') as mock:
            self.api.message_pr_with_type(pr_number, message_type, extra_text=extra_text, force_message=force_message)
            mock.assert_called_with(
                pr_number,
                github_api.PR_MESSAGE_FORMAT.format(
                    prefix=github_api.PR_PREFIX,
                    message=message_type.value,
                    extra_text=extra_text
                ),
                github_api.PR_MESSAGE_FORMAT.format(
                    prefix=github_api.PR_PREFIX,
                    message=message_type.value,
                    extra_text=extra_text
                ),
                force_message
            )
