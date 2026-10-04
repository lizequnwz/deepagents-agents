"""Application connector TLS without ambient logging or trust overrides."""

import ssl

import certifi


def tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    return context
