from __future__ import annotations

import pytest

from syndicateclaw.security.ssrf import SSRFError, validate_url


class TestSSRFBlocksPrivateIPs:
    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "192.168.0.100",
            "127.0.0.1",
            "127.0.0.2",
        ],
    )
    def test_ssrf_blocks_private_ips(self, ip: str) -> None:
        with pytest.raises(SSRFError, match="Blocked private IP"):
            validate_url(f"http://{ip}/api")

    def test_ssrf_blocks_link_local(self) -> None:
        with pytest.raises(SSRFError, match="Blocked private IP"):
            validate_url("http://169.254.169.254/latest/meta-data/")


class TestSSRFAllowsPublicIPs:
    @pytest.mark.parametrize(
        "ip",
        ["8.8.8.8", "1.1.1.1", "208.67.222.222", "93.184.216.34"],
    )
    def test_ssrf_allows_public_ips(self, ip: str) -> None:
        assert validate_url(f"https://{ip}/path") == ip


class TestSSRFBlocksLocalhost:
    def test_ssrf_blocks_localhost_ip(self) -> None:
        with pytest.raises(SSRFError, match="Blocked private IP"):
            validate_url("http://127.0.0.1:8080/admin")

    def test_ssrf_blocks_ipv6_loopback(self) -> None:
        with pytest.raises(SSRFError, match="Blocked private IP"):
            validate_url("http://[::1]/admin")


class TestSSRFSchemeValidation:
    def test_ssrf_rejects_ftp_scheme(self) -> None:
        with pytest.raises(SSRFError, match="Unsupported scheme"):
            validate_url("ftp://example.com/file")

    def test_ssrf_rejects_file_scheme(self) -> None:
        with pytest.raises(SSRFError, match="Unsupported scheme"):
            validate_url("file:///etc/passwd")

    def test_ssrf_allows_https(self) -> None:
        assert validate_url("https://8.8.8.8/dns") == "8.8.8.8"


class TestSSRFEdgeCases:
    def test_ssrf_missing_hostname(self) -> None:
        with pytest.raises(SSRFError, match="Missing hostname"):
            validate_url("http:///path")
