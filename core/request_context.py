from contextvars import ContextVar
request_ip = ContextVar('request_ip', default=None)
