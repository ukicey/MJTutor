class CoachError(Exception):
    """Base error with a message suitable for an MCP tool response."""


class InvalidLogError(CoachError):
    """Raised when an input is not a supported four-player hanchan log."""


class ReviewerError(CoachError):
    """Raised when mjai-reviewer or Mortal cannot produce a review."""


class ReviewNotFoundError(CoachError):
    """Raised when a locally stored review cannot be found."""


class ProfileItemNotFoundError(CoachError):
    """Raised when a profile item cannot be found."""
