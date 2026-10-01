import logging
import uuid
from ipaddress import ip_address
from core.request_context import request_ip
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger('oms.requests')


class RequestIDMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.request_id = uuid.uuid4().hex
        try:
            request_ip.set(str(ip_address(request.META.get('REMOTE_ADDR', ''))))
        except ValueError:
            request_ip.set(None)

    def process_response(self, request, response):
        response['X-Request-ID'] = request.request_id
        if response.status_code >= 500:
            logger.error('Request failed id=%s method=%s path=%s status=%s', request.request_id, request.method, request.path, response.status_code)
        request_ip.set(None)
        return response

    def process_exception(self, request, exception):
        logger.error('Unhandled error id=%s path=%s', request.request_id, request.path,
            exc_info=(type(exception), exception, exception.__traceback__))
