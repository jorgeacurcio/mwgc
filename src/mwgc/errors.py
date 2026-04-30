class MwgcError(Exception):
    """Base class for every error mwgc raises; catch this to handle any failure."""


class GpxParseError(MwgcError):
    pass


class FitBuildError(MwgcError):
    pass


class UploadError(MwgcError):
    pass


class AuthError(UploadError):
    pass


class DuplicateActivity(UploadError):
    pass
