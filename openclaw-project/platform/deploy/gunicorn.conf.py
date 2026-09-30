bind='127.0.0.1:18800'
workers=1
worker_class='sync'
threads=1
timeout=15
graceful_timeout=10
backlog=16
limit_request_line=2048
limit_request_fields=32
limit_request_field_size=2048
max_requests=1000
max_requests_jitter=20
accesslog=None
errorlog='-'
# Only the loopback TLS proxy may set the trusted protocol header.
forwarded_allow_ips='127.0.0.1,::1'
