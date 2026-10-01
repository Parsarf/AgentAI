import json
import ipaddress
import uuid
from django.db import DatabaseError
from django.http import JsonResponse
from django.contrib.auth import logout
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent, SuspiciousOperation
from .models import Identity
from .services import Denied, Limited, customer_scope, rate

class BoundaryMiddleware:
    def __init__(self, get_response): self.get_response=get_response
    def __call__(self, request):
        request.request_id=uuid.uuid4()
        peer=request.META.get('REMOTE_ADDR','127.0.0.1')
        request.client_ip=peer
        if peer in ['127.0.0.1','::1'] and request.META.get('HTTP_X_AGENTAI_CLIENT_IP'):
            try: request.client_ip=str(ipaddress.ip_address(request.META['HTTP_X_AGENTAI_CLIENT_IP']))
            except ValueError: return JsonResponse({'error':'invalid_proxy_identity'},status=400)
        try:
            request.get_host()
            if len(request.get_full_path()) > 2048 or int(request.META.get('CONTENT_LENGTH') or 0) > (200000 if request.path=='/v1/requests' else 8192):
                response=JsonResponse({'error':'request_too_large'},status=413)
            elif any(x in request.GET for x in ['account','account_id','tenant','tenant_id','session','session_id','native_session_ref','deployment_id']) or any(x in request.META for x in ['HTTP_X_ACCOUNT_ID','HTTP_X_TENANT_ID','HTTP_X_SESSION_ID','HTTP_X_AGENT_ID']):
                response=JsonResponse({'error':'routing_override_denied'},status=400)
            else: response=self.get_response(request)
        except (ValueError, SuspiciousOperation):
            response=JsonResponse({'error':'invalid_request'},status=400)
        except DatabaseError:
            response=JsonResponse({'error':'temporarily_unavailable'},status=503)
        response['Cache-Control']='no-store'
        response['X-Content-Type-Options']='nosniff'
        response['X-Frame-Options']='DENY'
        response['Content-Security-Policy']="default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        response['Referrer-Policy']='same-origin'
        response['X-Request-ID']=str(request.request_id)
        # No URL/query/body/cookie/header/exception text in customer logs.
        print(json.dumps({'event':'account_http','request_id':str(request.request_id),'status':response.status_code}),flush=True)
        return response

class AccountMiddleware:
    def __init__(self, get_response): self.get_response=get_response
    def __call__(self, request):
        request.account_id=None
        if request.user.is_authenticated:
            identity=Identity.objects.filter(user=request.user).first()
            if not identity or not identity.verified or identity.epoch != request.session.get('epoch') or identity.role=='service':
                logout(request)
            elif identity.role=='customer':
                try: request.account_id=customer_scope(request.user,request.session.get('epoch'))
                except Denied: logout(request)
        if request.user.is_authenticated:
            try:
                scope='api.read' if request.method in ['GET','HEAD'] else 'api.mutate'
                rate(scope,str(request.user.pk)+'|'+request.client_ip,60 if scope=='api.read' else 10,60)
            except Limited: return JsonResponse({'error':'rate_limited'},status=429,headers={'Retry-After':'60'})
        return self.get_response(request)
