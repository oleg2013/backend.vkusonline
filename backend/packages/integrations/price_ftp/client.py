from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime

import structlog

from packages.core.config import settings

logger = structlog.get_logger("price_ftp")

_FILE_RE = re.compile(r"last_import_data_(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})\.xml")

# KZ proxy host — FTP server is not directly reachable from Hetzner
_KZ_HOST = "root1@185.91.126.150"

_REMOTE_SCRIPT = '''
import sys, re
from ftplib import FTP
from io import BytesIO

ftp = FTP()
ftp.connect("{host}", {port}, timeout=60)
ftp.login("{user}", "{password}")

# Find latest file
files = ftp.nlst()
pattern = re.compile(r"last_import_data_(\\d{{4}})_(\\d{{2}})_(\\d{{2}})_(\\d{{2}})_(\\d{{2}})\\.xml")
candidates = []
for f in files:
    m = pattern.match(f)
    if m:
        candidates.append((f, int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5])))
if not candidates:
    sys.exit(1)
candidates.sort(key=lambda x: x[1:], reverse=True)
filename = candidates[0][0]

# Print filename on first line
print(filename, flush=True)

# Download and write raw bytes to stdout
buf = BytesIO()
ftp.retrbinary(f"RETR {{filename}}", buf.write)
ftp.quit()

sys.stdout.buffer.write(buf.getvalue())
'''


def _download_via_proxy() -> tuple[str, str] | None:
    """Download latest price XML via KZ proxy host."""
    script = _REMOTE_SCRIPT.format(
        host=settings.price_ftp_host,
        port=settings.price_ftp_port,
        user=settings.price_ftp_user,
        password=settings.price_ftp_password,
    )

    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", _KZ_HOST, "python3", "-"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=300,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        logger.error("price_ftp_proxy_failed", stderr=stderr[:500])
        return None

    raw = result.stdout
    # First line is filename (ASCII), rest is UTF-16 XML
    newline_pos = raw.index(b"\n")
    filename = raw[:newline_pos].decode("utf-8").strip()
    xml_bytes = raw[newline_pos + 1:]
    content = xml_bytes.decode("utf-16")

    logger.info("price_file_downloaded", filename=filename, size_chars=len(content), proxy=_KZ_HOST)
    return content, filename


async def fetch_latest_price_xml() -> tuple[str, str] | None:
    """Fetch latest price XML from FTP via KZ proxy."""
    return await asyncio.to_thread(_download_via_proxy)
