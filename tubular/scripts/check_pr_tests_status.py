#! /usr/bin/env python3

"""
Script to check the combined test status of a GitHub PR or commit SHA.
"""

import io
from os import path
import os
import logging
import sys
import click
import yaml

# Add top-level module path to sys.path before importing tubular code.
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from tubular.github_api import GitHubAPI  # pylint: disable=wrong-import-position
from tubular.utils import exactly_one_set  # pylint: disable=wrong-import-position

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
LOG = logging.getLogger(__name__)


@click.command("check_tests")
@click.option(
    '--org',
    help='Org from the GitHub repository URL of https://github.com/<org>/<repo>',
    default='edx'
)
@click.option(
    '--repo',
    help='Repo name from the GitHub repository URL of https://github.com/<org>/<repo>',
    required=True
)
@click.option(
    '--token',
    envvar='GIT_TOKEN',
    help='The github access token, see https://help.github.com/articles/creating-an-access-token-for-command-line-use/'
)
@click.option(
    '--input_file',
    help='YAML file from which to read a PR number to check, with the top-level key "pr_number"'
)
@click.option(
    '--pr_number',
    default=None,
    help='Pull request number to check.',
    type=int,
)
@click.option(
    '--commit_hash',
    help='Commit hash to check.',
)
@click.option(
    '--out_file',
    help=u"File location in which to write CI test status info.",
    type=click.File(mode='w', lazy=True),
    default=sys.stdout
)
@click.option(
    '--all-checks',
    help="Check all validation contexts, whehther it is required or not",
    is_flag=True,
    default=True
)
@click.option(
    '--exclude-contexts',
    help=u"Regex defining which validation contexts to exclude from this status check.",
    default="datreeio|Renovate|[Cc]odecov|Dependabot"
)
@click.option(
    '--include-contexts',
    help=u"Regex defining which validation contexts to include from this status check.",
    default=None
)
@click.option(
    '--min-checks',
    help=u"Minimum number of checks required to be present before allowing success. Set to 0 to disable.",
    default=1,
    type=int,
)
@click.option(
    '--fail-on-pending',
    help=u"Fail if any checks are still pending/in-progress. Recommended for deployment gates.",
    is_flag=True,
    default=True
)
def check_tests(
        org, repo, token, input_file, pr_number, commit_hash,
        out_file, all_checks, exclude_contexts, include_contexts,
        min_checks, fail_on_pending,
):
    """
    Check the current combined status of a GitHub PR/commit in a repo once.

    If tests have passed for the PR/commit, return a success.
    If any other status besides success (such as in-progress/pending), return a failure.

    If an input YAML file is specified, read the PR number from the file to check.
    If a PR number is specified, check that PR number's tests.
    If a commit hash is specified, check that commit hash's tests.
    """
    # Check for one and only one of the mutually-exclusive params.
    if not exactly_one_set((input_file, pr_number, commit_hash)):
        err_msg = \
            "Exactly one of input_file ({!r}), pr_number ({!r})," \
            " and commit_hash ({!r}) should be specified.".format(
                input_file,
                pr_number,
                commit_hash
            )
        LOG.error(err_msg)
        sys.exit(1)

    gh_utils = GitHubAPI(org, repo, token, exclude_contexts=exclude_contexts,
                         include_contexts=include_contexts, all_checks=all_checks)

    status_success = False
    if input_file:
        input_vars = yaml.safe_load(io.open(input_file, 'r'))
        pr_number = input_vars['pr_number']
        combined_status_success, test_statuses = gh_utils.check_combined_status_pull_request(pr_number)
        git_obj = 'PR #{}'.format(pr_number)
    elif pr_number:
        combined_status_success, test_statuses = gh_utils.check_combined_status_pull_request(pr_number)
        git_obj = 'PR #{}'.format(pr_number)
    elif commit_hash:
        combined_status_success, test_statuses = gh_utils.check_combined_status_commit(commit_hash)
        git_obj = 'commit hash {}'.format(commit_hash)

    LOG.info("{}: Combined status of {} is {}.".format(
        sys.argv[0], git_obj, "success" if combined_status_success else "failed"
    ))

    # Validate minimum check count to prevent race conditions where checks haven't started yet
    check_count = len(test_statuses)
    LOG.info("Found {} check(s) for {}.".format(check_count, git_obj))
    
    if check_count < min_checks:
        LOG.error(
            "DEPLOYMENT GATE FAILURE: Only {} check(s) found, but minimum of {} required. "
            "This may indicate checks haven't started yet or a configuration issue.".format(
                check_count, min_checks
            )
        )
        status_success = False
    else:
        ignore_list = ['GitHub Actions']
        
        # Track different failure types for better diagnostics
        pending_checks = []
        failed_checks = []
        successful_checks = []
        
        for test_name, details in test_statuses.items():
            try:
                _url, test_status_string = details.split(" ", 1)
            except ValueError:
                # Malformed details string - treat as failure
                LOG.error("Check \"{test_name}\" has malformed details: {details}".format(
                    test_name=test_name, details=details))
                failed_checks.append((test_name, "malformed_data"))
                continue
            
            # Check for pending/in-progress states
            # Note: 'none' handles the case where GitHub API returns None as a state value
            if test_status_string.lower() in ["pending", "in_progress", "queued", "waiting", "requested", "none"]:
                pending_checks.append((test_name, test_status_string))
                LOG.info("Check \"{test_name}\" is still running: {status}".format(
                    test_name=test_name, status=test_status_string))
            # Check for success/skipped states
            elif test_status_string.lower() in ["success", "skipped", "neutral"]:
                successful_checks.append(test_name)
                LOG.info("Check \"{test_name}\" passed: {status}".format(
                    test_name=test_name, status=test_status_string))
            # Everything else is a failure
            else:
                if test_name in ignore_list:
                    LOG.info("Ignoring failure of \"{test_name}\" because it is in the ignore list".format(
                        test_name=test_name))
                    successful_checks.append(test_name)
                else:
                    failed_checks.append((test_name, test_status_string))
                    LOG.error("Check \"{test_name}\" FAILED: {details}".format(
                        test_name=test_name, details=details))
        
        # Log summary
        LOG.info("Check summary: {} successful, {} pending, {} failed".format(
            len(successful_checks), len(pending_checks), len(failed_checks)
        ))
        
        # Determine overall status
        if failed_checks:
            LOG.error("DEPLOYMENT GATE FAILURE: {} check(s) failed: {}".format(
                len(failed_checks), [name for name, _ in failed_checks]
            ))
            status_success = False
        elif pending_checks and fail_on_pending:
            LOG.error(
                "DEPLOYMENT GATE FAILURE: {} check(s) still pending/in-progress: {}. "
                "Cannot proceed to deployment while checks are running.".format(
                    len(pending_checks), [name for name, _ in pending_checks]
                )
            )
            status_success = False
        elif pending_checks and not fail_on_pending:
            LOG.warning(
                "WARNING: {} check(s) still pending but --fail-on-pending is False: {}".format(
                    len(pending_checks), [name for name, _ in pending_checks]
                )
            )
            status_success = True
        else:
            LOG.info("All checks passed successfully.")
            status_success = True

    dirname = os.path.dirname(out_file.name)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    yaml.safe_dump(test_statuses, stream=out_file, width=1000)

    # An exit code of 0 means success and non-zero means failure.
    sys.exit(not status_success)


if __name__ == '__main__':
    check_tests()  # pylint: disable=no-value-for-parameter
