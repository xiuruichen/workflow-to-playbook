"""On-prem guarantees: where requests may go and where recordings may be stored."""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse


class SecurityError(RuntimeError):
    pass


def is_local_host(host: str) -> bool:
    """True if `host` resolves only to loopback or private-network addresses."""
    if not host:
        return False
    if host.lower() in ("localhost", "localhost.localdomain"):
        return True
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    for addr in addrs:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return bool(addrs)


def check_endpoint(url: str, allow_cloud: bool) -> None:
    """Refuse to send screenshots anywhere except this machine / the private network."""
    host = urlparse(url).hostname or ""
    if allow_cloud or is_local_host(host):
        return
    raise SecurityError(
        f"Refusing to send screenshots to {host or url}: it is not on this machine or the local network. "
        "Analysis is local by default. To use a cloud model anyway, set ALLOW_CLOUD=true (and PROVIDER=gemini)."
    )


_SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "icloud drive", "mobile documents", "box sync")


def synced_folder(path: Path) -> str | None:
    """Name of the cloud-sync service whose folder contains `path`, if any."""
    resolved = Path(path).expanduser().resolve()
    candidates = [os.environ.get(k) for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")]
    for root in filter(None, candidates):
        try:
            resolved.relative_to(Path(root).resolve())
            return "OneDrive"
        except ValueError:
            pass
    for part in resolved.parts:
        low = part.lower()
        for marker in _SYNC_MARKERS:
            if low == marker or low.startswith(marker + " -") or low.startswith(marker + "-"):
                return marker.title()
    return None


def check_storage(path: Path, allow_synced: bool) -> None:
    service = synced_folder(path)
    if service and not allow_synced:
        raise SecurityError(
            f"{path} is inside a {service} folder, so recordings would be uploaded to the cloud. "
            "Use the default local data folder (unset SESSIONS_DIR), or set ALLOW_SYNCED_DIR=true to override."
        )
