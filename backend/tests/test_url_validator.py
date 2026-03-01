import pytest

from app.services.url_validator import validate_youtube_url


class TestValidUrls:
    def test_standard_watch_url(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLtest"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_short_url(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_short_url_with_params(self):
        url = "https://youtu.be/dQw4w9WgXcQ?t=30"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_mobile_url(self):
        url = "https://m.youtube.com/watch?v=dQw4w9WgXcQ"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_no_www(self):
        url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_embed_url(self):
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_http_scheme(self):
        url = "http://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert validate_youtube_url(url) == "dQw4w9WgXcQ"

    def test_video_id_with_hyphens_and_underscores(self):
        url = "https://www.youtube.com/watch?v=a-b_c1D2E3f"
        assert validate_youtube_url(url) == "a-b_c1D2E3f"


class TestInvalidUrls:
    def test_wrong_host(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("https://vimeo.com/123456")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("")

    def test_not_a_url(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("not a url at all")

    def test_no_video_id(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("https://www.youtube.com/watch")

    def test_short_video_id(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("https://www.youtube.com/watch?v=short")

    def test_long_video_id(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("https://www.youtube.com/watch?v=toolongvideoid123")

    def test_ftp_scheme(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("ftp://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_youtube_channel_url(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("https://www.youtube.com/@channel")

    def test_malicious_host(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("https://evil-youtube.com/watch?v=dQw4w9WgXcQ")

    def test_video_id_with_special_chars(self):
        with pytest.raises(ValueError, match="INVALID_URL"):
            validate_youtube_url("https://www.youtube.com/watch?v=abc!@#$%^&*(")
