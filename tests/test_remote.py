import gzip
import json
from unittest.mock import Mock

import pytest

from paprika_recipes.constants import APP_NAME, PAPRIKA_APP_USER_AGENT, USER_AGENT
from paprika_recipes.exceptions import RequestError
from paprika_recipes.remote import Remote, RemotePhoto, RemoteRecipe


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


class TestPhotoWireFormat:
    """The upload spellings observed from the app's own traffic."""

    def authenticated(self, json_value) -> Remote:
        remote = build_remote(build_response(json_value))
        remote._bearer_token = "a-token"

        return remote

    def sent_files(self, remote: Remote) -> dict:
        return remote._session.request.call_args_list[0].kwargs["files"]

    def sent_data(self, remote: Remote) -> dict:
        return json.loads(gzip.decompress(self.sent_files(remote)["data"]))

    def test_an_absent_photo_is_spelled_null(self):
        """The app sends `null`, never an empty string, for a recipe with no
        photo -- and never sends `photo_url` at all."""
        remote = self.authenticated({"result": {"uid": "A"}})

        remote.upload_recipe(RemoteRecipe(uid="A", name="Test"))

        data = self.sent_data(remote)
        assert data["photo"] is None
        assert data["photo_hash"] is None
        assert data["photo_large"] is None
        assert "photo_url" not in data

    def test_a_new_photos_bytes_ride_along_with_the_recipe(self):
        remote = self.authenticated({"result": {"uid": "A"}})
        recipe = RemoteRecipe(
            uid="A", name="Test", photo="NEW.jpg", photo_hash="DIGEST"
        )

        remote.upload_recipe(recipe, photo_upload=b"thumbnail bytes")

        files = self.sent_files(remote)
        assert files["photo_upload"] == ("NEW.jpg", b"thumbnail bytes", "image/jpeg")
        assert self.sent_data(remote)["photo"] == "NEW.jpg"

    def test_a_gallery_photo_uploads_the_apps_own_fields(self):
        remote = self.authenticated({"result": True})
        photo = RemotePhoto(
            uid="G", recipe_uid="A", filename="G.jpg", name="1", hash="DIGEST"
        )

        remote.upload_photo(photo, b"image bytes")

        method, url = remote._session.request.call_args.args
        assert (method, url) == (
            "post",
            "https://www.paprikaapp.com/api/v2/sync/photo/G/",
        )

        data = self.sent_data(remote)
        assert set(data) == {
            "uid",
            "recipe_uid",
            "filename",
            "name",
            "order_flag",
            "hash",
            "deleted",
        }
        assert data["deleted"] is False
        assert self.sent_files(remote)["photo_upload"] == (
            "G.jpg",
            b"image bytes",
            "image/jpeg",
        )

    def test_a_gallery_deletion_sends_no_image(self):
        remote = self.authenticated({"result": True})
        photo = RemotePhoto(uid="G", recipe_uid="A", filename="G.jpg", deleted=True)

        remote.upload_photo(photo)

        assert "photo_upload" not in self.sent_files(remote)
        assert self.sent_data(remote)["deleted"] is True

    def test_get_photos_reads_the_gallery(self):
        remote = self.authenticated(
            {
                "result": [
                    {
                        "uid": "G",
                        "recipe_uid": "A",
                        "filename": "G.jpg",
                        "photo_url": "https://example.com/G.jpg",
                        "a_field_we_have_never_heard_of": 7,
                    }
                ]
            }
        )

        (photo,) = remote.get_photos()

        assert photo.uid == "G"
        assert photo.recipe_uid == "A"
        assert photo.photo_url == "https://example.com/G.jpg"
