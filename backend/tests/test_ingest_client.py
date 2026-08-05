import tempfile
import unittest
from pathlib import Path

import requests

from app.services.ingest_client import IngestClient, IngestError


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.sent_bodies = []

    def request(self, method, url, **kwargs):
        data = kwargs.get("data")
        if data is not None and not isinstance(data, dict):
            self.sent_bodies.append(b"".join(data))
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def client(session):
    return IngestClient(
        api_base_url="http://ingest.test",
        api_authorization="Basic api-token",
        hfs_upload_url="http://hfs.test/ScanImages",
        hfs_username="hfs-user",
        hfs_password="hfs-password",
        connect_timeout=1,
        read_timeout=2,
        session=session,
    )


class IngestClientTests(unittest.TestCase):
    def test_owned_session_does_not_inherit_system_proxy(self):
        owned = IngestClient(
            api_base_url="http://ingest.test",
            api_authorization="Basic api-token",
            hfs_upload_url="http://hfs.test/ScanImages",
            hfs_username="hfs-user",
            hfs_password="hfs-password",
            connect_timeout=1,
            read_timeout=2,
        )
        try:
            self.assertFalse(owned.session.trust_env)
        finally:
            owned.close()

    def test_check_requires_boolean_result(self):
        session = FakeSession([FakeResponse({"result": False})])

        self.assertFalse(client(session).check_zipfilename_ingested("G1.zip"))
        _, url, kwargs = session.calls[0]
        self.assertEqual(url, "http://ingest.test/api/stat/check-zip-file-ingested")
        self.assertEqual(kwargs["data"], {"zip_filename": "G1.zip"})
        self.assertEqual(kwargs["timeout"], (1, 2))
        self.assertNotIn("auth", kwargs)
        self.assertEqual(kwargs["headers"]["Authorization"], "Basic api-token")

    def test_check_fails_closed_on_ambiguous_response(self):
        session = FakeSession([FakeResponse({"result": "false"})])

        with self.assertRaisesRegex(IngestError, "boolean result"):
            client(session).check_zipfilename_ingested("G1.zip")

    def test_generate_requires_zip_id(self):
        session = FakeSession([FakeResponse({"zip_id": "ZIP-123"})])
        self.assertEqual(client(session).generate_zip_id("PROJECT", "ZA"), "ZIP-123")

        missing = FakeSession([FakeResponse({"success": True})])
        with self.assertRaisesRegex(IngestError, "zip_id"):
            client(missing).generate_zip_id("PROJECT", "ZA")

    def test_http_auth_error_is_configuration_error(self):
        session = FakeSession([FakeResponse({}, status_code=401)])

        with self.assertRaises(IngestError) as raised:
            client(session).check_zipfilename_ingested("G1.zip")

        self.assertTrue(raised.exception.configuration)
        self.assertEqual(raised.exception.status_code, 401)

    def test_server_error_is_transient(self):
        session = FakeSession([FakeResponse({}, status_code=503)])

        with self.assertRaises(IngestError) as raised:
            client(session).generate_zip_id("PROJECT", "ZA")

        self.assertTrue(raised.exception.transient)

    def test_confirm_must_be_explicitly_successful(self):
        successful = FakeSession([FakeResponse({"success": True})])
        client(successful).confirm_zip_uploaded("a" * 64, "ZIP-1", "G1.zip")

        ambiguous = FakeSession([FakeResponse({"message": "received"})])
        with self.assertRaisesRegex(IngestError, "not explicitly successful") as raised:
            client(ambiguous).confirm_zip_uploaded("a" * 64, "ZIP-1", "G1.zip")
        self.assertEqual(raised.exception.status_code, 200)
        self.assertEqual(raised.exception.response_payload, {"message": "received"})

    def test_confirm_accepts_valid_file_signature_response(self):
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "file_name": "G1.zip",
                        "is_match": True,
                        "message": "file signature is valid",
                        "trace_id": "trace-123",
                    }
                )
            ]
        )

        client(session).confirm_zip_uploaded("a" * 64, "ZIP-1", "G1.zip")

    def test_confirm_rejects_invalid_file_signature(self):
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "file_name": "G1.zip",
                        "is_match": False,
                        "message": "file signature is invalid",
                        "trace_id": "trace-123",
                    }
                )
            ]
        )

        with self.assertRaisesRegex(IngestError, "not explicitly successful"):
            client(session).confirm_zip_uploaded("a" * 64, "ZIP-1", "G1.zip")

    def test_confirm_response_redacts_sensitive_fields(self):
        session = FakeSession(
            [FakeResponse({"message": "received", "token": "do-not-record"})]
        )

        with self.assertRaises(IngestError) as raised:
            client(session).confirm_zip_uploaded("a" * 64, "ZIP-1", "G1.zip")

        self.assertEqual(
            raised.exception.response_payload,
            {"message": "received", "token": "<redacted>"},
        )

    def test_upload_streams_the_zip_with_basic_auth(self):
        session = FakeSession([FakeResponse("ok")])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "G1.zip.uploading"
            path.write_bytes(b"zip-content")

            result = client(session).upload_zip(path)
            _, url, kwargs = session.calls[0]
            sent = session.sent_bodies[0]

        self.assertEqual(url, "http://hfs.test/ScanImages")
        self.assertIn(b"zip-content", sent)
        self.assertIn(b'filename="G1.zip"', sent)
        self.assertNotIn(b'filename="G1.zip.uploading"', sent)
        self.assertIn("Content-Length", kwargs["headers"])
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["auth"].username, "hfs-user")
        self.assertEqual(kwargs["auth"].password, "hfs-password")
        self.assertGreater(result.duration_s, 0)

    def test_multipart_stream_has_length_without_chunked_transfer_encoding(self):
        session = FakeSession([FakeResponse("ok")])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "G1.zip.uploading"
            path.write_bytes(b"zip-content")

            client(session).upload_zip(path)
            _, url, kwargs = session.calls[0]
            prepared = requests.Request(
                "POST",
                url,
                data=kwargs["data"],
                headers=kwargs["headers"],
            ).prepare()

        self.assertIn("Content-Length", prepared.headers)
        self.assertNotIn("Transfer-Encoding", prepared.headers)

    def test_upload_closes_multipart_stream_after_connection_error(self):
        class FailingStreamingSession:
            body = None

            def request(self, _method, _url, **kwargs):
                self.body = kwargs["data"]
                stream = iter(self.body)
                next(stream)  # multipart prefix
                next(stream)  # first file chunk; the file is now open
                raise requests.exceptions.ProxyError("proxy reset")

        session = FailingStreamingSession()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "G1.zip.uploading"
            destination = Path(temporary) / "G1.zip"
            source.write_bytes(b"zip-content")

            with self.assertRaisesRegex(IngestError, "ProxyError"):
                client(session).upload_zip(source)

            self.assertTrue(session.body.closed)
            source.rename(destination)
            self.assertTrue(destination.is_file())


if __name__ == "__main__":
    unittest.main()
