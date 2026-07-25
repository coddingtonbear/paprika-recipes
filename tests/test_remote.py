from unittest.mock import Mock

import pytest

from paprika_recipes.constants import APP_NAME, PAPRIKA_APP_USER_AGENT, USER_AGENT
from paprika_recipes.exceptions import RequestError
from paprika_recipes.remote import Remote


def build_remote(response: Mock) -> Remote:
    remote = Remote("someone@example.com", "password")
    remote._session = Mock()
    remote._session.request.return_value = response
    return remote


def build_response(json_value, text="") -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.text = text
    if isinstance(json_value, Exception):
        response.json.side_effect = json_value
    else:
        response.json.return_value = json_value
    return response


class TestRequestErrors:
    def test_reports_message_from_api_error(self):
        remote = build_remote(
            build_response({"error": {"code": 0, "message": "Unrecognized client."}})
        )

        with pytest.raises(RequestError, match="Unrecognized client."):
            remote._request("get", "/api/v2/sync/recipes/", authenticated=False)

    def test_reports_something_when_error_has_no_message(self):
        remote = build_remote(build_response({"error": {}}))

        with pytest.raises(RequestError, match="Unknown error"):
            remote._request("get", "/api/v2/sync/recipes/", authenticated=False)

    def test_reports_non_json_responses(self):
        remote = build_remote(
            build_response(ValueError("not json"), text="<html>gateway timeout</html>")
        )

        with pytest.raises(RequestError, match="Expected a JSON response"):
            remote._request("get", "/api/v2/sync/recipes/", authenticated=False)

    def test_returns_result_on_success(self):
        response = build_response({"result": []})
        remote = build_remote(response)

        assert (
            remote._request("get", "/api/v2/sync/recipes/", authenticated=False)
            is response
        )


class TestRetries:
    def test_session_is_configured_with_retries(self):
        remote = Remote("someone@example.com", "password")

        adapter = remote._session.get_adapter("https://www.paprikaapp.com")
        assert adapter.max_retries.total == 5


class TestUserAgent:
    def test_user_agent_begins_with_the_string_the_v2_api_recognises(self):
        """The v2 API matches on a prefix, so ours has to start with theirs.

        Anything else earns `Unrecognized client.` on every request, login
        included, so this is the difference between a working program and one
        that cannot reach the account at all.
        """
        assert USER_AGENT.startswith(PAPRIKA_APP_USER_AGENT)

    def test_user_agent_also_identifies_this_program(self):
        assert APP_NAME in USER_AGENT.removeprefix(PAPRIKA_APP_USER_AGENT)

    def test_session_sends_the_user_agent(self):
        remote = Remote("someone@example.com", "password")

        assert remote._session.headers["User-Agent"] == USER_AGENT


class TestLogin:
    def test_logs_in_against_v2_and_keeps_the_token(self):
        remote = build_remote(build_response({"result": {"token": "a-token"}}))

        assert remote.bearer_token == "a-token"

        method, path = remote._session.request.call_args.args
        assert (method, path) == (
            "post",
            "https://www.paprikaapp.com/api/v2/account/login/",
        )

    def test_login_sends_credentials_and_no_receipt(self):
        remote = build_remote(build_response({"result": {"token": "a-token"}}))

        remote.bearer_token

        kwargs = remote._session.request.call_args.kwargs
        assert kwargs["data"] == {
            "email": "someone@example.com",
            "password": "password",
        }

    def test_login_is_not_itself_authenticated(self):
        remote = build_remote(build_response({"result": {"token": "a-token"}}))

        remote.bearer_token

        kwargs = remote._session.request.call_args.kwargs
        assert "Authorization" not in kwargs.get("headers", {})
