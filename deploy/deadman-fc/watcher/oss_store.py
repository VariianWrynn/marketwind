"""
Real OSS adapter for the deadman watchdog state layer.

The ``credentials`` object comes from the FC runtime ``context.credentials``.
The exact attribute names (``access_key_id`` / ``access_key_secret`` /
``security_token``) must be confirmed against the FC Python runtime at deploy
time — this is an integration seam, unverified offline.
"""

import oss2


class OssObjectStore:  # pragma: no cover
    def __init__(self, endpoint: str, bucket: str, credentials) -> None:
        auth = oss2.StsAuth(
            credentials.access_key_id,
            credentials.access_key_secret,
            credentials.security_token,
        )
        self._bucket = oss2.Bucket(auth, "https://" + endpoint, bucket)

    def get(self, key: str) -> bytes | None:
        try:
            return self._bucket.get_object(key).read()
        except oss2.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self._bucket.put_object(key, data)
