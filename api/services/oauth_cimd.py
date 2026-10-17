"""Client ID Metadata Document (CIMD) support for MCP OAuth (I-072).

MCP authorization spec 2025-11-25: when a client has no prior relationship
with this authorization server, its client_id is an HTTPS URL pointing at a
JSON metadata document. The document is fetched, validated and cached as a
row in community.oauth_clients, so foreign keys and the token chain keep
working unchanged for all three client identity kinds:

- CIMD       client_id is an HTTPS URL (recommended for unknown agents)
- DCR        dynamically registered via /oauth/register (behavior unchanged)
- registered pre-registered client_id rows (source_type default)

Fetches are SSRF-hardened: DNS results must all be public addresses, the
connection is pinned to a validated IP (no rebinding), redirects are never
followed, the body is capped, and each document host is rate-limited.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import text

from ..core import rate_limit
from .oauth import OAuthProtocolError, _valid_redirect_uri

logger = logging.getLogger(__name__)

CLIENT_ID_MAX_LENGTH = 300  # 与 oauth_clients.client_id 现有上限一致
DOCUMENT_MAX_BYTES = 5 * 1024
FETCH_TIMEOUT_SECONDS = 5.0
# 手写 HTTP 读取的上限: 行缓冲(asyncio StreamReader 的 limit, 状态行/头
# 单行超限抛 ValueError)、头区块行数与总字节数。合法响应远低于这些值;
# 恶意或损坏端点返回超长无换行走廊时按协议错误拒绝, 不让任何形态逃成
# 未分类异常(500 且 host 失败桶不计数)。
READ_LINE_LIMIT_BYTES = 16 * 1024
HEADER_MAX_LINES = 100
HEADER_MAX_BYTES = 32 * 1024
CACHE_AGE_MIN_SECONDS = 300        # 5 分钟
CACHE_AGE_MAX_SECONDS = 24 * 3600  # 24 小时
CACHE_AGE_DEFAULT_SECONDS = 3600   # 无 Cache-Control 时的缺省
FETCH_URL_LIMIT_PER_HOUR = 20        # 按完整 client_id URL 分桶, 每次拉取尝试都计
FETCH_HOST_FAIL_LIMIT_PER_HOUR = 300  # 按 host 分桶, 只计失败的拉取(非 200/超限/校验不过)
FETCH_ANON_IP_LIMIT_PER_HOUR = 30   # 匿名触发拉取时按来源 IP 分桶(拿得到 IP 才计)
FETCH_USER_LIMIT_PER_HOUR = 30      # 登录用户触发拉取时按人分桶
_REDIRECT_URI_MAX = 2000
_MAX_URIS = 10
_MAX_NAME = 160

_MAX_AGE_RE = re.compile(r"max-age\s*=\s*(\d+)", re.IGNORECASE)


def is_cimd_client_id(client_id: str) -> bool:
    """client_id 以 https:// 开头即视为 Client ID Metadata Document URL."""
    return client_id.startswith("https://")


def validate_cimd_url(value: str) -> None:
    """CIMD URL 语法闸: https、默认端口、有 path、无 fragment、无用户信息。"""
    if len(value) > CLIENT_ID_MAX_LENGTH or not value.isascii():
        raise OAuthProtocolError(
            "invalid_request",
            "client_id URL is too long or contains non-ASCII characters.",
        )
    if any(ch.isspace() or ord(ch) < 0x21 for ch in value):
        raise OAuthProtocolError(
            "invalid_request",
            "client_id URL contains whitespace or control characters.",
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise OAuthProtocolError(
            "invalid_request", "client_id is not a valid URL."
        ) from exc
    if parsed.scheme != "https":
        raise OAuthProtocolError(
            "invalid_request", "client_id URL must use HTTPS."
        )
    if parsed.fragment or parsed.username or parsed.password:
        raise OAuthProtocolError(
            "invalid_request",
            "client_id URL must not contain a fragment or user information.",
        )
    if not parsed.hostname or not parsed.path:
        raise OAuthProtocolError(
            "invalid_request", "client_id URL must include a path."
        )
    if port is not None and port != 443:
        raise OAuthProtocolError(
            "invalid_request", "client_id URL must use the default HTTPS port."
        )


_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")  # 运营商级 NAT: 部分
# Python 版本的 is_private 不含该段, 显式拦截


def _ip_allowed(value: str) -> bool:
    """公网单播地址才放行; 私网/回环/链路本地/保留/组播/CGNAT 一律拒绝。

    IPv4-mapped、6to4、Teredo 内嵌的 IPv4 地址先解包再判, 防止用
    ::ffff:10.0.0.1 之类写法绕过 IPv4 拦截。
    """
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
        elif ip.teredo is not None:
            ip = ip.teredo[0]
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or ip in _CGNAT_NETWORK
    )


def _prefer_ipv4(addresses: list[str]) -> list[str]:
    """IPv4 优先(生产机无 IPv6 出口, AAAA 随机选中必失败); 去重保持首现顺序。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in addresses:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return sorted(ordered, key=lambda ip: ipaddress.ip_address(ip).version == 6)


async def _resolve_addresses(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return _prefer_ipv4([sockaddr[0] for _, _, _, _, sockaddr in infos])


@dataclass
class FetchedDocument:
    status: int
    content_type: str
    cache_control: str | None
    body: bytes


async def _fetch_document(url: str) -> FetchedDocument:
    """SSRF 加固的 HTTPS GET: 解析 DNS → 校验全部 IP → 逐个地址建连。

    只发一次请求(不跟随重定向), 总耗时(含逐地址重试)受 5 秒上限约束,
    响应体上限 5 KB。TLS 证书按 URL 的 host 校验(server_hostname),
    连接却钉在已校验的 IP 上, DNS rebinding 在两次解析之间切换地址也无效。
    IPv4 优先(同族保持解析顺序): 生产机无 IPv6 出口, 混合解析时
    随机选中 AAAA 会导致必然失败, 所以逐个地址尝试到成功为止。
    """
    parsed = urlsplit(url)
    host = parsed.hostname
    port = parsed.port or 443
    try:
        addresses = await _resolve_addresses(host, port)
    except OSError as exc:
        raise OAuthProtocolError(
            "invalid_request", "client_id host could not be resolved."
        ) from exc
    if not addresses or any(not _ip_allowed(ip) for ip in addresses):
        raise OAuthProtocolError(
            "invalid_request",
            "client_id host resolves to a forbidden address.",
        )
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    host_header = host if port == 443 else f"{host}:{port}"
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Accept: application/json\r\n"
        "Accept-Encoding: identity\r\n"
        "User-Agent: hgs-oauth-cimd/1\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")

    async def _attempt(address: str) -> FetchedDocument:
        reader, writer = await asyncio.open_connection(
            address, port,
            ssl=ssl.create_default_context(),
            server_hostname=host,
            limit=READ_LINE_LIMIT_BYTES,
        )
        try:
            writer.write(request)
            await writer.drain()
            status_line = await reader.readline()
            try:
                status = int(status_line.split(None, 2)[1])
            except (IndexError, ValueError) as exc:
                raise OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document response was malformed.",
                ) from exc
            headers: dict[str, str] = {}
            header_lines = 0
            header_bytes = 0
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                header_lines += 1
                header_bytes += len(line)
                if header_lines > HEADER_MAX_LINES or header_bytes > HEADER_MAX_BYTES:
                    raise OAuthProtocolError(
                        "invalid_request",
                        "Client ID Metadata Document response was malformed.",
                    )
                name, _, value = line.partition(b":")
                headers[name.decode("latin-1").strip().lower()] = (
                    value.decode("latin-1").strip()
                )
            if headers.get("transfer-encoding", "").lower() == "chunked":
                body = await _read_chunked(reader, DOCUMENT_MAX_BYTES + 1)
            else:
                body = await _read_body(reader, headers.get("content-length"))
            return FetchedDocument(
                status=status,
                content_type=headers.get("content-type", ""),
                cache_control=headers.get("cache-control"),
                body=body,
            )
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _do_fetch() -> FetchedDocument:
        last_error: OSError | None = None
        for address in addresses:
            try:
                return await _attempt(address)
            except OSError as exc:
                # 建连/握手/读失败(TLS 错误是 OSError 子类) → 尝试下一个地址
                last_error = exc
                continue
        raise OAuthProtocolError(
            "invalid_request",
            "Client ID Metadata Document could not be fetched.",
        ) from last_error

    try:
        document = await asyncio.wait_for(_do_fetch(), FETCH_TIMEOUT_SECONDS)
    except OAuthProtocolError:
        raise
    except (OSError, asyncio.TimeoutError, ValueError) as exc:
        raise OAuthProtocolError(
            "invalid_request",
            "Client ID Metadata Document could not be fetched.",
        ) from exc
    return document


async def _read_body(
    reader: asyncio.StreamReader, content_length: str | None
) -> bytes:
    """按 Content-Length 或 EOF 读完整响应体; 单次 read() 可能返回部分数据。

    有 Content-Length: 超过 5 KB 直接拒绝; 用 readexactly 收满声明的字节数
    (流提前 EOF 抛 IncompleteReadError → 视为畸形响应)。
    无 Content-Length: 循环 read() 到 EOF, 期间超过 5 KB 即拒绝。
    """
    if content_length is not None:
        raw = content_length.strip()
        try:
            declared = int(raw)
        except ValueError as exc:
            raise OAuthProtocolError(
                "invalid_request",
                "Client ID Metadata Document response was malformed.",
            ) from exc
        if declared < 0:
            raise OAuthProtocolError(
                "invalid_request",
                "Client ID Metadata Document response was malformed.",
            )
        if declared > DOCUMENT_MAX_BYTES:
            raise OAuthProtocolError(
                "invalid_request", "Client ID Metadata Document exceeds 5 KB."
            )
        try:
            return await reader.readexactly(declared)
        except asyncio.IncompleteReadError as exc:
            raise OAuthProtocolError(
                "invalid_request",
                "Client ID Metadata Document response was malformed.",
            ) from exc
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > DOCUMENT_MAX_BYTES:
            raise OAuthProtocolError(
                "invalid_request", "Client ID Metadata Document exceeds 5 KB."
            )
        chunks.append(chunk)


async def _read_chunked(reader: asyncio.StreamReader, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        size_line = await reader.readline()
        try:
            size = int(size_line.split(b";")[0].strip() or b"0", 16)
        except ValueError as exc:
            raise OAuthProtocolError(
                "invalid_request",
                "Client ID Metadata Document response was malformed.",
            ) from exc
        if size == 0:
            try:
                await reader.readexactly(2)  # 终止 chunk 后的 CRLF
            except asyncio.IncompleteReadError as exc:
                raise OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document response was malformed.",
                ) from exc
            return b"".join(chunks)
        total += size
        if total > limit:
            raise OAuthProtocolError(
                "invalid_request", "Client ID Metadata Document exceeds 5 KB."
            )
        try:
            chunks.append(await reader.readexactly(size))
            await reader.readexactly(2)  # CRLF
        except asyncio.IncompleteReadError as exc:
            raise OAuthProtocolError(
                "invalid_request",
                "Client ID Metadata Document response was malformed.",
            ) from exc


def cache_age_seconds(cache_control: str | None) -> int:
    """文档缓存期: 遵守 max-age, 夹在 5 分钟到 24 小时之间; 无头按 1 小时。"""
    match = _MAX_AGE_RE.search(cache_control or "")
    if not match:
        return CACHE_AGE_DEFAULT_SECONDS
    return max(CACHE_AGE_MIN_SECONDS, min(int(match.group(1)), CACHE_AGE_MAX_SECONDS))


def validate_cimd_document(client_id: str, doc: object) -> dict:
    """校验文档内容并归一化; 返回可直接入库的列值 dict。"""
    if not isinstance(doc, dict):
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "Client ID Metadata Document must be a JSON object.",
        )
    if doc.get("client_id") != client_id:
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "Document client_id does not match its own URL.",
        )
    host = urlsplit(client_id).hostname or ""

    client_name = doc.get("client_name")
    if client_name is None or client_name == "":
        client_name = host
    if not isinstance(client_name, str):
        raise OAuthProtocolError(
            "invalid_client_metadata", "client_name must be a string."
        )
    client_name = client_name.strip()[:_MAX_NAME] or host

    redirect_uris = doc.get("redirect_uris")
    if (
        not isinstance(redirect_uris, list)
        or not 1 <= len(redirect_uris) <= _MAX_URIS
        or any(not isinstance(uri, str) for uri in redirect_uris)
    ):
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "redirect_uris must contain 1-10 string entries.",
        )
    if any(
        len(uri) > _REDIRECT_URI_MAX or not _valid_redirect_uri(uri)
        for uri in redirect_uris
    ):
        raise OAuthProtocolError(
            "invalid_redirect_uri",
            "Every redirect URI must be at most 2000 characters and use HTTPS, "
            "except localhost loopback URIs.",
        )

    auth_method = doc.get("token_endpoint_auth_method")
    if auth_method not in (None, "none"):
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "This authorization server registers public clients only.",
        )

    # grant_types / response_types 规则与 DCR(register_client)逐条一致。
    grants = ["authorization_code"] if doc.get("grant_types") is None \
        else doc["grant_types"]
    if (
        not isinstance(grants, list)
        or "authorization_code" not in grants
        or any(not isinstance(value, str)
               or value not in ("authorization_code", "refresh_token")
               for value in grants)
    ):
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "grant_types must include authorization_code and contain only "
            "supported values.",
        )
    responses = ["code"] if doc.get("response_types") is None \
        else doc["response_types"]
    if not isinstance(responses, list) or responses != ["code"]:
        raise OAuthProtocolError(
            "invalid_client_metadata", "Only response_type=code is supported."
        )

    def _https_uri(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > _REDIRECT_URI_MAX:
            raise OAuthProtocolError(
                "invalid_client_metadata", "client_uri and logo_uri must be HTTPS URLs."
            )
        try:
            parsed = urlsplit(value)
            port_ok = parsed.port is None or parsed.port == 443
        except ValueError:
            raise OAuthProtocolError(
                "invalid_client_metadata",
                "client_uri and logo_uri must be HTTPS URLs.",
            ) from None
        if parsed.scheme != "https" or not parsed.hostname \
                or not port_ok or parsed.fragment:
            raise OAuthProtocolError(
                "invalid_client_metadata",
                "client_uri and logo_uri must be HTTPS URLs.",
            )
        return value

    return {
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": grants,
        "response_types": responses,
        "client_uri": _https_uri(doc.get("client_uri")),
        "logo_uri": _https_uri(doc.get("logo_uri")),
    }


async def _load_cimd_row(db, client_id: str):
    return (await db.execute(text("""
        SELECT client_id,client_name,redirect_uris,grant_types,source_type,
               metadata_cache_until,disabled_at
        FROM community.oauth_clients
        WHERE client_id=:client_id
    """), {"client_id": client_id})).mappings().first()


async def ensure_client_for_authorize(
    db,
    *,
    client_id: str,
    redirect_uri: str,
    actor_id: int | None,
    client_ip: str | None,
    fetcher=None,
    now=None,
) -> dict:
    """/authorize 前置解析 CIMD client_id: 缓存命中直接用, 过期/缺失才拉取。

    拉取失败一律拒绝本次授权, 不用过期缓存兜底。返回
    {client_id, client_name, redirect_uris, grant_types, host, source_type};
    redirect_uri 不在文档内时抛 invalid_request。
    """
    validate_cimd_url(client_id)
    host = urlsplit(client_id).hostname or ""
    row = await _load_cimd_row(db, client_id)

    if row is not None and row["source_type"] != "cimd":
        # URL 形状但来源不是 CIMD 的行按其登记内容处理, 不发起拉取。
        if row["disabled_at"] is not None:
            raise OAuthProtocolError("unauthorized_client", "Unknown OAuth client.")
        if redirect_uri not in tuple(row["redirect_uris"] or ()):
            raise OAuthProtocolError(
                "invalid_request", "redirect_uri is not registered."
            )
        # 已登记客户端(即使 client_id 恰为 URL 形状)授权页显示不变: 不带 host。
        return {
            "client_id": row["client_id"],
            "client_name": row["client_name"] or "MCP client",
            "redirect_uris": list(row["redirect_uris"] or ()),
            "grant_types": list(row["grant_types"] or ()),
            "host": None,
            "source_type": row["source_type"],
        }
    if row is not None and row["disabled_at"] is not None:
        # 管理员停用的 CIMD 客户端: 直接拒绝, 不浪费一次受限流的外部拉取。
        raise OAuthProtocolError("unauthorized_client", "Unknown OAuth client.")

    fresh = (
        row is not None
        and row["disabled_at"] is None
        and row["metadata_cache_until"] is not None
        and row["metadata_cache_until"] > (now or datetime.now(timezone.utc))
    )
    if not fresh:
        # 限流(1.3/1.4): 每次拉取尝试按完整 client_id URL 分桶(同 host 的
        # 随机路径各自计数, 攻击者无法耗尽真实客户端的配额)。匿名且有
        # 来源 IP 时再加 IP 桶; 登录用户按人分桶 —— URL 桶挡不住"同 host
        # 换路径"的横向铺开, 按人限次才挡得住。拿不到匿名 IP 时不落全站
        # 共用桶, 只走 URL 桶并告警。
        await rate_limit.enforce(
            "oauth-cimd-url", client_id, FETCH_URL_LIMIT_PER_HOUR, 3600)
        if actor_id is None:
            if client_ip:
                await rate_limit.enforce(
                    "oauth-cimd-fetch-anon", client_ip,
                    FETCH_ANON_IP_LIMIT_PER_HOUR, 3600)
            else:
                logger.warning(
                    "CIMD anonymous fetch without client IP "
                    "(no x-real-ip): anonymous IP limit skipped, "
                    "url bucket only, client_id=%s", client_id)
        else:
            await rate_limit.enforce(
                "oauth-cimd-fetch-user", str(actor_id),
                FETCH_USER_LIMIT_PER_HOUR, 3600)
        # host 失败桶预检: 已满说明该 host 近一小时失败次数已到上限,
        # 直接拒绝, 不再对外发请求(该桶只在失败后计数, 预检只读不写)。
        if not await rate_limit.check(
                "oauth-cimd-host-fail", host,
                FETCH_HOST_FAIL_LIMIT_PER_HOUR, 3600):
            raise rate_limit.RateLimited("该站点近期文档拉取失败过多，请稍后再试")
        try:
            fetch = fetcher or _fetch_document
            try:
                document = await fetch(client_id)
            except ValueError as exc:
                raise OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document response was malformed.",
                ) from exc
            # 状态码/大小/类型校验放在消费侧, 对任何 fetcher(含测试桩)一致生效。
            if document.status != 200:
                raise OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document request did not return HTTP 200 "
                    f"(got {document.status}). Redirects are not followed.",
                )
            if len(document.body) > DOCUMENT_MAX_BYTES:
                raise OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document exceeds 5 KB.",
                )
            if "json" not in document.content_type.split(";")[0].strip().lower():
                raise OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document must be served as JSON.",
                )
            try:
                parsed = json.loads(document.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document is not valid JSON.",
                ) from exc
            values = validate_cimd_document(client_id, parsed)
        except OAuthProtocolError:
            # host 级宽松上限只计失败的拉取(非 200/超限/校验不过)。
            # 成功的拉取写入缓存不会重复触发, 天然不计入。
            await rate_limit.enforce(
                "oauth-cimd-host-fail", host,
                FETCH_HOST_FAIL_LIMIT_PER_HOUR, 3600)
            raise
        cache_until = (now or datetime.now(timezone.utc)) + timedelta(
            seconds=cache_age_seconds(document.cache_control))
        await db.execute(text("""
            INSERT INTO community.oauth_clients(
                client_id,client_name,redirect_uris,
                token_endpoint_auth_method,grant_types,response_types,
                application_type,source_type,metadata_fetched_at,
                metadata_cache_until,client_uri,logo_uri
            ) VALUES (
                :client_id,:client_name,:redirect_uris,
                'none',:grant_types,:response_types,
                'web','cimd',now(),:cache_until,:client_uri,:logo_uri
            )
            ON CONFLICT (client_id) DO UPDATE SET
                client_name=EXCLUDED.client_name,
                redirect_uris=EXCLUDED.redirect_uris,
                grant_types=EXCLUDED.grant_types,
                response_types=EXCLUDED.response_types,
                source_type='cimd',
                metadata_fetched_at=now(),
                metadata_cache_until=EXCLUDED.metadata_cache_until,
                client_uri=EXCLUDED.client_uri,
                logo_uri=EXCLUDED.logo_uri
            WHERE community.oauth_clients.source_type='cimd'
              AND community.oauth_clients.disabled_at IS NULL
        """), {
            "client_id": client_id,
            "client_name": values["client_name"],
            "redirect_uris": values["redirect_uris"],
            "grant_types": values["grant_types"],
            "response_types": values["response_types"],
            "cache_until": cache_until,
            "client_uri": values["client_uri"],
            "logo_uri": values["logo_uri"],
        })
        await db.commit()
        row = await _load_cimd_row(db, client_id)
        if row is None or row["source_type"] != "cimd" or row["disabled_at"] is not None:
            raise OAuthProtocolError(
                "unauthorized_client", "Unknown OAuth client.")

    if redirect_uri not in tuple(row["redirect_uris"] or ()):
        raise OAuthProtocolError(
            "invalid_request", "redirect_uri is not registered."
        )
    return {
        "client_id": row["client_id"],
        "client_name": row["client_name"] or "MCP client",
        "redirect_uris": list(row["redirect_uris"] or ()),
        "grant_types": list(row["grant_types"] or ()),
        "host": host,
        "source_type": "cimd",
    }


__all__ = [
    "is_cimd_client_id",
    "validate_cimd_url",
    "validate_cimd_document",
    "cache_age_seconds",
    "ensure_client_for_authorize",
]
