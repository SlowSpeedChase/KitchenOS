"""Tests for Instagram Reel metadata diagnosis.

6 of 7 failures in the 2026-07-29 batch run — and 195 across the 190 logs in
failures/ — were "Could not fetch Instagram Reel metadata", categorized
"unknown". The underlying yt-dlp error says exactly what to do (pass cookies),
but the pipeline threw that away, so a one-line .env fix stayed invisible
through 195 failures.
"""
import pytest
from unittest.mock import patch

import yt_dlp

import main
from main import get_instagram_metadata, get_instagram_metadata_with_diagnosis


# The real yt-dlp message observed on 2026-07-29, trimmed.
EMPTY_MEDIA_ERROR = (
    "ERROR: [Instagram] DYSU8nkh5fu: Instagram sent an empty media response. "
    "Check if this post is accessible in your browser without being logged-in. "
    "If it is not, then use --cookies-from-browser or --cookies for the authentication."
)

RATE_LIMIT_ERROR = (
    "ERROR: [Instagram] ABC: You need to log in to access this content"
)

GENUINELY_GONE_ERROR = (
    "ERROR: [Instagram] ABC: Requested content is not available, rate-limit reached "
    "or login required"
)


def _raise_download_error(msg):
    def _boom(*args, **kwargs):
        raise yt_dlp.utils.DownloadError(msg)
    return _boom


class TestAuthDiagnosis:

    def test_empty_media_response_names_the_cookie_env_vars(self):
        """The fix is a .env line — the error must say which one."""
        with patch('main.yt_dlp.YoutubeDL') as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.extract_info = (
                _raise_download_error(EMPTY_MEDIA_ERROR)
            )
            with patch.object(main, 'INSTAGRAM_COOKIES_FROM_BROWSER', None), \
                 patch.object(main, 'INSTAGRAM_COOKIES_FILE', None):
                meta, reason = get_instagram_metadata_with_diagnosis(
                    "https://www.instagram.com/reel/DYSU8nkh5fu/"
                )
        assert meta is None
        assert "INSTAGRAM_COOKIES_FROM_BROWSER" in reason
        assert "log" in reason.lower() or "auth" in reason.lower()

    @pytest.mark.parametrize("err", [RATE_LIMIT_ERROR, GENUINELY_GONE_ERROR])
    def test_other_auth_shapes_also_detected(self, err):
        with patch('main.yt_dlp.YoutubeDL') as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.extract_info = (
                _raise_download_error(err)
            )
            with patch.object(main, 'INSTAGRAM_COOKIES_FROM_BROWSER', None), \
                 patch.object(main, 'INSTAGRAM_COOKIES_FILE', None):
                meta, reason = get_instagram_metadata_with_diagnosis(
                    "https://www.instagram.com/reel/ABC/"
                )
        assert meta is None
        assert "INSTAGRAM_COOKIES_FROM_BROWSER" in reason

    def test_configured_cookies_get_a_different_message(self):
        """If cookies ARE set and it still fails, 'set cookies' is useless advice."""
        with patch('main.yt_dlp.YoutubeDL') as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.extract_info = (
                _raise_download_error(EMPTY_MEDIA_ERROR)
            )
            with patch.object(main, 'INSTAGRAM_COOKIES_FROM_BROWSER', 'chrome'), \
                 patch.object(main, 'INSTAGRAM_COOKIES_FILE', None):
                meta, reason = get_instagram_metadata_with_diagnosis(
                    "https://www.instagram.com/reel/ABC/"
                )
        assert meta is None
        assert "chrome" in reason
        # Telling someone to set a var they already set is the bug, not the fix.
        assert "expired" in reason.lower() or "stale" in reason.lower() \
            or "re-authenticate" in reason.lower()

    def test_unrelated_error_is_not_reported_as_auth(self):
        with patch('main.yt_dlp.YoutubeDL') as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.extract_info = (
                _raise_download_error("ERROR: Unable to download webpage: 500 Server Error")
            )
            meta, reason = get_instagram_metadata_with_diagnosis(
                "https://www.instagram.com/reel/ABC/"
            )
        assert meta is None
        assert "INSTAGRAM_COOKIES_FROM_BROWSER" not in reason


class TestSuccessAndContract:

    def test_success_returns_metadata_and_no_reason(self):
        info = {
            'title': 'Larb Bowls',
            'channel': 'somechef',
            'description': 'Recipe in caption',
            'thumbnail': 'https://example.com/t.jpg',
        }
        with patch('main.yt_dlp.YoutubeDL') as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.extract_info = (
                lambda *a, **k: info
            )
            meta, reason = get_instagram_metadata_with_diagnosis(
                "https://www.instagram.com/reel/ABC/"
            )
        assert reason is None
        assert meta['title'] == 'Larb Bowls'
        assert meta['channel'] == 'somechef'

    def test_legacy_wrapper_still_returns_dict_or_none(self):
        """get_instagram_metadata keeps its original contract."""
        with patch('main.yt_dlp.YoutubeDL') as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.extract_info = (
                _raise_download_error(EMPTY_MEDIA_ERROR)
            )
            assert get_instagram_metadata("https://www.instagram.com/reel/ABC/") is None
