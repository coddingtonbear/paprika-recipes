class PaprikaException(Exception):
    pass


class PaprikaError(PaprikaException):
    pass


class AuthenticationError(PaprikaError):
    pass


class RequestError(PaprikaError):
    pass


class PaprikaUserError(PaprikaException):
    pass
