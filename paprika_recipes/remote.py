from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .cache import Cache, NullCache
from .constants import DEFAULT_DOMAIN, USER_AGENT
from .exceptions import PaprikaError, RequestError
from .recipe import BaseRecipe
from .types import RecipeManager, RemoteRecipeIdentifier


@dataclass
class RemoteRecipe(BaseRecipe):
    in_trash: bool = False
    is_pinned: bool = False
    on_favorites: bool = False
    on_grocery_list: str | None = None
    photo_url: str | None = None
    scale: str | None = None


class Remote(RecipeManager):
    _bearer_token: str | None = None

    _domain: str
    _email: str
    _password: str

    def __init__(
        self,
        email: str,
        password: str,
        domain: str = DEFAULT_DOMAIN,
        cache: Cache | None = None,
    ):
        super().__init__()
        self._email = email
        self._password = password
        self._domain = domain
        self._cache = cache if cache else NullCache()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=5,
                    backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "POST"],
                )
            ),
        )

    def __iter__(self) -> Iterator[RemoteRecipe]:
        yield from self.recipes

    @property
    def recipes(self) -> Iterable[RemoteRecipe]:
        for recipe in self._get_remote_recipe_identifiers():
            yield self.get_recipe_by_id(recipe.uid, recipe.hash)

    def get_recipe_by_id(self, id: str, hash: str) -> RemoteRecipe:
        all_fields = RemoteRecipe.get_all_fields()

        data: dict = {}

        if self._cache.is_cached(id, hash):
            data = self._cache.read_from_cache(id, hash)

        if not data:
            recipe_response = self._request("get", f"/api/v2/sync/recipe/{id}/")

            data = recipe_response.json().get("result", {})

            self._cache.store_in_cache(id, hash, data)
            self._cache.save()

        return RemoteRecipe(
            **{
                field.name: data[field.name]
                for field in all_fields
                if field.name in data
            }
        )

    def count(self) -> int:
        return len(self._get_remote_recipe_identifiers())

    def get_recipe_index(self) -> dict[str, str]:
        """Map every recipe's uid to the hash the server currently holds for it.

        One request covers the whole account, which makes this the cheap way
        of asking which recipes have moved since we last looked.
        """
        return {
            recipe.uid: recipe.hash for recipe in self._get_remote_recipe_identifiers()
        }

    def download_photo(self, url: str) -> bytes:
        """Fetch the bytes of a recipe's photo.

        Photo URLs point at signed object storage rather than at the API, so
        this is a plain GET: no bearer token, and no JSON envelope around
        the image.
        """
        try:
            response = self._session.get(url)
            response.raise_for_status()
        except requests.RequestException as e:
            raise RequestError(f"The photo at {url} could not be downloaded: {e}")

        return response.content

    def upload_recipe(self, recipe: RemoteRecipe) -> RemoteRecipe:
        recipe.update_hash()

        self._request(
            "post",
            f"/api/v2/sync/recipe/{recipe.uid}/",
            files={"data": recipe.as_paprikarecipe()},
        )

        return self.get_recipe_by_id(recipe.uid, recipe.hash)

    def add_recipe(self, recipe: RemoteRecipe) -> RemoteRecipe:
        return self.upload_recipe(recipe)

    def _get_remote_recipe_identifiers(self) -> list[RemoteRecipeIdentifier]:
        recipes = self._request("get", "/api/v2/sync/recipes/")

        return [
            RemoteRecipeIdentifier(**recipe)
            for recipe in recipes.json().get("result", [])
        ]

    def _request(self, method, path, authenticated=True, **kwargs):
        if authenticated:
            kwargs.setdefault("headers", {})[
                "Authorization"
            ] = f"Bearer {self.bearer_token}"
        result = self._session.request(
            method, f"https://{self._domain}{path}", **kwargs
        )
        result.raise_for_status()

        try:
            data = result.json()
        except ValueError:
            raise RequestError(
                f"Expected a JSON response from {method.upper()} {path}, "
                f"but received: {result.text[:200]}"
            )

        if "error" in data:
            message = (data.get("error") or {}).get("message") or "Unknown error"
            raise RequestError(f"{method.upper()} {path} returned an error: {message}")

        return result

    @property
    def bearer_token(self):
        if not self._bearer_token:
            try:
                # Paprika's own app posts a third field here, `receipt`, holding
                # the App Store receipt for its iOS purchase.  Omitting it is
                # fine -- the field is only validated when it is present and
                # non-empty, and the token comes back with the same scope and
                # account mode either way -- which is just as well, since there
                # is no way for this program to obtain one.
                result = self._request(
                    "post",
                    "/api/v2/account/login/",
                    data={"email": self._email, "password": self._password},
                    authenticated=False,
                )

                token = result.json().get("result", {}).get("token")
                if not token:
                    raise PaprikaError(
                        f"No bearer token found in response: {result.content}"
                    )

                self._bearer_token = token
            except requests.HTTPError as e:
                raise PaprikaError(
                    f"Authentication URL returned unexpected status: {e}"
                )

        return self._bearer_token

    def notify(self):
        """Asks the API to notify recipe apps that changes have occurred."""
        self._request("post", "/api/v2/sync/notify/")

    def __str__(self):
        return f"Remote Paprika Recipes ({self.count()} recipes)"
