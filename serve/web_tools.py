"""Bounded public HTTPS reads for the dashboard's read-only MCP tools."""
import ipaddress
import socket
import urllib.request
import urllib.parse
import re
import html
import xml.etree.ElementTree as ET

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def read_public(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Usa un URL HTTPS pubblico senza credenziali')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Gli indirizzi locali e privati non sono accessibili')
    request = urllib.request.Request(url, headers={'User-Agent': 'Hydra One-StargateLab/1.0'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        kind = response.headers.get_content_type()
        if kind not in ('text/html', 'text/plain', 'application/xml', 'text/xml', 'application/rss+xml'):
            raise ValueError('Formato della pagina non supportato')
        raw = response.read(512000)
        return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')

def web_call(name, arguments):
    if name == 'read_web_page':
        url = arguments.get('url', '')
        page = read_public(url)
        page = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', page, flags=re.S|re.I)
        text = html.unescape(re.sub('<[^>]+>', ' ', page))
        return {'url': url, 'text': re.sub(r'\s+', ' ', text).strip()[:16000]}
    query = arguments.get('query')
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 300:
        raise ValueError('La ricerca deve contenere da 1 a 300 caratteri')
    url = 'https://www.bing.com/search?format=rss&q=' + urllib.parse.quote(query)
    root = ET.fromstring(read_public(url))
    return {'query': query, 'sources': [{'title': row.findtext('title'), 'url': row.findtext('link'),
             'description': row.findtext('description')} for row in root.findall('./channel/item')[:6]]}
