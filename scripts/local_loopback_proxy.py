#!/usr/bin/env python3
"""Temporary loopback-only TCP proxy to a literal Tailscale target."""

import argparse
import ipaddress
import json
import select
import socket
import socketserver
import threading


TAILSCALE_IPV4 = ipaddress.ip_network("100.64.0.0/10")


def validate_proxy_endpoints(listen_host, target_host):
    listen_address = ipaddress.ip_address(listen_host)
    target_address = ipaddress.ip_address(target_host)
    if not listen_address.is_loopback:
        raise ValueError("Proxy listener must be a literal loopback address")
    if target_address.version != 4 or target_address not in TAILSCALE_IPV4:
        raise ValueError("Proxy target must be a literal Tailscale IPv4 address")
    return str(listen_address), str(target_address)


class ThreadingProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def handler_for(target_host, target_port):
    class ProxyHandler(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection(
                (target_host, target_port), timeout=10
            ) as upstream:
                self.request.settimeout(None)
                upstream.settimeout(None)
                peers = {
                    self.request: upstream,
                    upstream: self.request,
                }
                while True:
                    readable, _, exceptional = select.select(
                        list(peers), [], list(peers), 30
                    )
                    if exceptional:
                        return
                    for source in readable:
                        data = source.recv(64 * 1024)
                        if not data:
                            return
                        peers[source].sendall(data)

    return ProxyHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--lifetime-seconds", type=int, default=8 * 60 * 60)
    args = parser.parse_args()
    listen_host, target_host = validate_proxy_endpoints(
        args.listen_host, args.target_host
    )
    for name, port in (
        ("listen_port", args.listen_port),
        ("target_port", args.target_port),
    ):
        if not 1 <= port <= 65535:
            raise ValueError(f"Invalid {name}")
    if not 1 <= args.lifetime_seconds <= 24 * 60 * 60:
        raise ValueError("Proxy lifetime must be between one second and 24 hours")

    with ThreadingProxyServer(
        (listen_host, args.listen_port),
        handler_for(target_host, args.target_port),
    ) as server:
        expiry = threading.Timer(args.lifetime_seconds, server.shutdown)
        expiry.daemon = True
        expiry.start()
        print(
            json.dumps(
                {
                    "ok": True,
                    "listen": f"{listen_host}:{args.listen_port}",
                    "target": f"{target_host}:{args.target_port}",
                    "lifetime_seconds": args.lifetime_seconds,
                }
            ),
            flush=True,
        )
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            expiry.cancel()


if __name__ == "__main__":
    main()
