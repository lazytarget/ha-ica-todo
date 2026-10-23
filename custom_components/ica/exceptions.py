"""Exceptions raised by the ICA API client."""


class IcaAuthError(Exception):
    """Login to ICA failed, e.g. due to an invalid personal ID number or PIN."""
