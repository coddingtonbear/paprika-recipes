from unittest.mock import Mock

import pytest

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
