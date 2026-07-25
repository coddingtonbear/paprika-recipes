import gzip
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field, fields

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


@dataclass
class RemotePhoto:
    """A photo in a recipe's gallery, as Paprika's photo sync endpoint sees it.

    This is a different thing from the recipe's own `photo` field.  That one
    is a square thumbnail carried on the recipe itself; these are the
    pictures the app shows on a recipe's photos page, each an object of its
    own.  When the app adds a photo to a recipe it uploads both -- the
    thumbnail onto the recipe, and the picture itself into the gallery, with
    the recipe's `photo_large` naming the gallery copy.

    The field names and their spelling are the wire format.
    """

    uid: str = ""
    recipe_uid: str = ""
    filename: str = ""
    #: The photo's display name; the app numbers them ("1", "2", ...).
    name: str = ""
    order_flag: int = 0
    #: An opaque sync token, like a recipe's `hash`: the server keeps
    #: whatever the client sends, and other clients use it to notice change.
    hash: str = ""
    deleted: bool = False
    #: Where to download the image from; only ever present in responses.
    photo_url: str | None = field(default=None, compare=False)

    def as_upload(self) -> bytes:
        """The gzipped JSON document the photo endpoint expects."""
        data = asdict(self)
        del data["photo_url"]

        return gzip.compress(json.dumps(data).encode("utf-8"))


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

    def upload_recipe(
        self, recipe: RemoteRecipe, photo_upload: bytes | None = None
    ) -> RemoteRecipe:
        """Send a recipe to the server, optionally with a new photo's bytes.

        `photo_upload` is the image for the recipe's `photo` field: when the
        photo is changing, the app sends its bytes in the same request that
        names it, and so do we.  The caller is expected to have set `photo`
        to the image's filename and `photo_hash` to a digest of exactly
        these bytes.
        """
        recipe.update_hash()

        files: dict = {"data": _recipe_upload(recipe)}

        if photo_upload is not None:
            files["photo_upload"] = (recipe.photo, photo_upload, "image/jpeg")

        self._request("post", f"/api/v2/sync/recipe/{recipe.uid}/", files=files)

        return self.get_recipe_by_id(recipe.uid, recipe.hash)

    def upload_photo(self, photo: RemotePhoto, image: bytes | None = None) -> None:
        """Send a gallery photo to the server -- or, with `deleted` set, take
        one down; a deletion carries no image bytes."""
        files: dict = {"data": photo.as_upload()}

        if image is not None:
            files["photo_upload"] = (photo.filename, image, "image/jpeg")

        self._request("post", f"/api/v2/sync/photo/{photo.uid}/", files=files)

    def get_photos(self) -> list[RemotePhoto]:
        """Every gallery photo the account holds, across all its recipes."""
        response = self._request("get", "/api/v2/sync/photos/")
        known = {field.name for field in fields(RemotePhoto)}

        return [
            RemotePhoto(**{key: value for key, value in item.items() if key in known})
            for item in response.json().get("result", [])
        ]

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


def _recipe_upload(recipe: RemoteRecipe) -> bytes:
    """The gzipped JSON document the recipe endpoint expects.

    Two spelling matters, both observed from the app's own uploads rather
    than documented anywhere: an absent photo is `null`, never an empty
    string, and `photo_url` is not sent at all -- it only ever appears in
    responses, where the server fills it with a signed download link.
    """
    data = recipe.as_dict()
    data.pop("photo_url", None)

    for name in ("photo", "photo_hash", "photo_large"):
        data[name] = data[name] or None

    return gzip.compress(json.dumps(data).encode("utf-8"))
