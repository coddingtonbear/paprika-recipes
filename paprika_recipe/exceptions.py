class PaprikaError(Exception):
    pass


class AuthenticationError(PaprikaError):
    pass


class RequestError(PaprikaError):
    pass
