from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional

import requests

from .cache import Cache, NullCache
from .exceptions import PaprikaError, RequestError
from .recipe import BaseRecipe
from .types import RecipeManager, RemoteRecipeIdentifier


@dataclass
class RemoteRecipe(BaseRecipe):
    in_trash: bool = False
    is_pinned: bool = False
    on_favorites: bool = False
    on_grocery_list: Optional[str] = None
    photo_url: Optional[str] = None
    scale: Optional[str] = None


class Remote(RecipeManager):
    _bearer_token: Optional[str] = None

    _domain: str
    _email: str
    _password: str

    def __init__(
        self,
        email: str,
        password: str,
        domain: str = "www.paprikaapp.com",
        cache: Optional[Cache] = None,
    ):
        super().__init__()
        self._email = email
        self._password = password
        self._domain = domain
        self._cache = cache if cache else NullCache()

    def __iter__(self) -> Iterator[RemoteRecipe]:
        yield from self.recipes

    @property
    def recipes(self) -> Iterable[RemoteRecipe]:
        for recipe in self._get_remote_recipe_identifiers():
            yield self.get_recipe_by_id(recipe.uid, recipe.hash)

    def get_recipe_by_id(self, id: str, hash: str) -> RemoteRecipe:
        all_fields = RemoteRecipe.get_all_fields()

        data: Dict = {}

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

    def _get_remote_recipe_identifiers(self) -> List[RemoteRecipeIdentifier]:
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
        result = requests.request(method, f"https://{self._domain}{path}", **kwargs)
        result.raise_for_status()

        if "error" in result.json():
            raise RequestError()

        return result

    @property
    def bearer_token(self):
        if not self._bearer_token:
            try:
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
