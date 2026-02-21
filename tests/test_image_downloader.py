import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

from lib.image_downloader import download_image


class TestDownloadImage:
    def test_downloads_image_to_path(self):
        """Should download image and save to specified path"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.jpg"
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/jpeg"}
            mock_response.iter_content = Mock(return_value=[b"fake image data"])
            mock_response.raise_for_status = Mock()
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)

            with patch("lib.image_downloader.requests.get", return_value=mock_response):
                result = download_image("https://example.com/photo.jpg", target)

            assert result == target
            assert target.exists()
            assert target.read_bytes() == b"fake image data"

    def test_creates_parent_directory(self):
        """Should create parent directories if they don't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "Images" / "test.jpg"
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/jpeg"}
            mock_response.iter_content = Mock(return_value=[b"data"])
            mock_response.raise_for_status = Mock()
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)

            with patch("lib.image_downloader.requests.get", return_value=mock_response):
                result = download_image("https://example.com/photo.jpg", target)

            assert target.parent.exists()
            assert target.exists()

    def test_returns_none_on_failure(self):
        """Should return None on download failure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.jpg"
            with patch("lib.image_downloader.requests.get", side_effect=Exception("Network error")):
                result = download_image("https://example.com/photo.jpg", target)

            assert result is None
            assert not target.exists()

    def test_returns_none_for_non_image_content(self):
        """Should return None if response is not an image"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.jpg"
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}
            mock_response.raise_for_status = Mock()
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)

            with patch("lib.image_downloader.requests.get", return_value=mock_response):
                result = download_image("https://example.com/photo.jpg", target)

            assert result is None
