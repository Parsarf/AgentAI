import json
import uuid
from functools import wraps
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection, transaction, DatabaseError, IntegrityError
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django_otp import verify_token, login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from .models import Identity, Audit, EmailJob
from .services import Denied, Limited, audit, rate, token_for, deliver, consume, create_invite, operator_scope, revoke, models_f_epoch

def csrf_failure(request, reason=''):
    return JsonResponse({'error':'csrf_denied'},status=403)

def endpoint(methods, fields=(), field_limits=None):
    def decorate(fn):
        @wraps(fn)
        def view(request,*args,**kwargs):
            if request.method not in methods: return JsonResponse({'error':'method_not_allowed'},status=405)
            try:
                request.input={}
                previous_key=request.session.session_key
                previous_user=request.user
                if request.method=='POST':
                    if request.content_type=='application/json':
                        data=json.loads(request.body or b'{}')
                    elif request.content_type=='application/x-www-form-urlencoded':
                        data=request.POST.dict(); data.pop('csrfmiddlewaretoken',None)
                    else: return JsonResponse({'error':'unsupported_media_type'},status=415)
                    if not isinstance(data,dict) or set(data)-set(fields) or any(not isinstance(value,str) or len(value)>(field_limits or {}).get(key,512) for key,value in data.items()):
                        return JsonResponse({'error':'invalid_request'},status=400)
                    request.input=data
                response=fn(request,*args,**kwargs)
                if request.method=='POST' and request.content_type=='application/x-www-form-urlencoded' and response.status_code<400:
                    if fn.__name__ in ['requests','cancel']: return HttpResponseRedirect('/account/requests/')
                    if fn.__name__=='signin': return HttpResponseRedirect('/account/mfa/' if request.user.identity.role=='operator' else '/account/')
                    if fn.__name__ in ['signout','revoke_sessions','finish']: return HttpResponseRedirect('/account/login/')
                    return render(request,'accounts/result.html',{'pending':fn.__name__=='recovery'})
                return response
            except Limited: return JsonResponse({'error':'rate_limited'},status=429,headers={'Retry-After':'900'})
            except Denied:
                try: audit(request.user.pk if request.user.is_authenticated else 'anonymous',request.account_id,'route','access.denied','denied',request.request_id)
                except DatabaseError: return JsonResponse({'error':'temporarily_unavailable'},status=503)
                return JsonResponse({'error':'unavailable'},status=404)
            except (ValidationError, ValueError, json.JSONDecodeError): return JsonResponse({'error':'invalid_request'},status=400)
            except (DatabaseError, IntegrityError):
                # A rolled-back login must not be re-saved by SessionMiddleware.
                from django.contrib.sessions.backends.db import SessionStore
                from django.contrib.auth.models import AnonymousUser
                request.session=SessionStore(session_key=previous_key); request.user=previous_user
                return JsonResponse({'error':'temporarily_unavailable'},status=503)
        return view
    return decorate

def customer(request):
    if not request.user.is_authenticated: return JsonResponse({'error':'authentication_required'},status=401)
    if not request.account_id: raise Denied()
    return None

@endpoint(['GET'])
def health(request): return JsonResponse({'status':'ok','service':'accounts'})

@endpoint(['GET'])
def ready(request):
    from agentai_platform.store import Store
    foundation=Store(settings.DATABASES['default']['NAME']).ready()
    try: Identity.objects.exists(); identity=True
    except DatabaseError: identity=False
    return JsonResponse({'foundation_ready':foundation,'identity_ready':identity,'customer_ready':False,
                         'execution_enabled':False,'mail_configured':settings.EMAIL_BACKEND=='django.core.mail.backends.smtp.EmailBackend'},status=200 if foundation and identity else 503)

@endpoint(['GET'])
def account_page(request, page='home'):
    if page not in ['home','login','recover','reset','activate','mfa']: raise Denied()
    if page=='home':
        denied=customer(request)
        if denied: return HttpResponseRedirect('/account/login/')
        with connection.cursor() as c:
            c.execute('SELECT state FROM deployments WHERE account_id=%s ORDER BY generation DESC LIMIT 1',[request.account_id]); row=c.fetchone()
        return render(request,'accounts/home.html',{'email':request.user.email,'deployment_state':row[0] if row else 'not provisioned'})
    return render(request,'accounts/form.html',{'page':page})

@endpoint(['POST'], ['email','password'])
def signin(request):
    email=request.input.get('email','').strip().lower()
    rate('login.ip',request.client_ip,30,900)
    rate('auth.pair',email+'|'+request.client_ip,5,900)
    user=User.objects.filter(email__iexact=email).first()
    authenticated=authenticate(request, username=user.username if user else 'nonexistent',password=request.input.get('password',''))
    identity=Identity.objects.filter(user=authenticated,verified=True).first() if authenticated else None
    if not identity or identity.role=='service':
        audit('anonymous',None,'identity','identity.login','denied',request.request_id)
        return JsonResponse({'error':'invalid_credentials'},status=401)
    if identity.role=='customer':
        from .services import customer_scope
        try: customer_scope(authenticated,identity.epoch)
        except Denied:
            audit('anonymous',None,'identity','identity.login','denied',request.request_id)
            return JsonResponse({'error':'invalid_credentials'},status=401)
    with transaction.atomic():
        op=uuid.uuid4(); audit(user.pk,identity.account_id,user.pk,'identity.login','pending',request.request_id,op)
        login(request,authenticated); request.session.cycle_key(); request.session['epoch']=identity.epoch
        request.session.set_expiry(settings.SESSION_COOKIE_AGE); request.session.save()
        audit(user.pk,identity.account_id,user.pk,'identity.login','completed',request.request_id,op)
    return JsonResponse({'signed_in':True,'mfa_required':identity.role=='operator','execution_enabled':False})

@endpoint(['POST'])
def signout(request):
    if not request.user.is_authenticated: return JsonResponse({'signed_out':True})
    identity=request.user.identity
    with transaction.atomic():
        op=uuid.uuid4(); audit(request.user.pk,identity.account_id,request.user.pk,'identity.logout','pending',request.request_id,op)
        logout(request)
        audit(identity.user_id,identity.account_id,identity.user_id,'identity.logout','completed',request.request_id,op)
    return JsonResponse({'signed_out':True})

@endpoint(['POST'])
def revoke_sessions(request):
    denied=customer(request)
    if denied: return denied
    with transaction.atomic():
        op=uuid.uuid4(); actor=request.user.pk
        audit(actor,request.account_id,actor,'identity.revoke_sessions','pending',request.request_id,op)
        Identity.objects.filter(user=request.user).update(epoch=models_f_epoch())
        logout(request)
        audit(actor,request.account_id,actor,'identity.revoke_sessions','completed',request.request_id,op)
    return JsonResponse({'sessions_revoked':True})

@endpoint(['POST'], ['email'])
def recovery(request):
    email=request.input.get('email','').strip().lower()
    rate('recovery.ip',request.client_ip,20,900)
    rate('auth.pair',email+'|'+request.client_ip,5,900)
    # Per-email throttling has the same public response for every address.
    try: rate('recovery.email',email,3,900)
    except Limited: return JsonResponse({'status':'If eligible, account instructions will be sent.'},status=202)
    user=User.objects.filter(email__iexact=email,identity__role='customer').first()
    if user:
        from .services import customer_scope
        identity=user.identity
        try:
            if identity.verified: customer_scope(user,identity.epoch)
            else:
                with connection.cursor() as c:
                    c.execute("SELECT 1 FROM accounts a JOIN memberships m ON a.id=m.account_id WHERE a.id=%s AND a.status='active' AND m.actor_id=%s AND m.status='active' AND m.role='customer'",[identity.account_id,str(user.pk)])
                    if not c.fetchone(): raise Denied()
            purpose='recovery' if identity.verified else 'onboarding'
            with transaction.atomic():
                op=uuid.uuid4(); audit(user.pk,identity.account_id,user.pk,'identity.request_'+purpose,'pending',request.request_id,op)
                EmailJob.objects.create(user=user,purpose=purpose)
                audit(user.pk,identity.account_id,user.pk,'identity.request_'+purpose,'completed',request.request_id,op)
        except Denied: pass
    return JsonResponse({'status':'If eligible, account instructions will be sent.'},status=202)

@endpoint(['POST'], ['code','password'])
def finish(request,purpose):
    rate('token.ip',request.client_ip,5,900)
    consume(request.input.get('code',''),purpose,request.input.get('password',''),request.request_id)
    return JsonResponse({'completed':True,'next':'/account/login/'})

@endpoint(['POST'], ['code'])
def mfa(request):
    if not request.user.is_authenticated: return JsonResponse({'error':'authentication_required'},status=401)
    identity=request.user.identity
    if identity.role!='operator' or not identity.verified: raise Denied()
    rate('mfa.user',request.user.pk,8)
    device=TOTPDevice.objects.filter(user=request.user,confirmed=True).first()
    if not device: raise Denied()
    with transaction.atomic():
        op=uuid.uuid4(); audit(request.user.pk,None,request.user.pk,'identity.mfa','pending',request.request_id,op)
        verified=verify_token(request.user,device.persistent_id,request.input.get('code',''))
        if not verified:
            audit(request.user.pk,None,request.user.pk,'identity.mfa','denied',request.request_id,op)
            return JsonResponse({'error':'invalid_code'},status=401)
        otp_login(request,verified); request.session.cycle_key(); request.session.save()
        audit(request.user.pk,None,request.user.pk,'identity.mfa','completed',request.request_id,op)
    return JsonResponse({'verified':True})

@endpoint(['GET'])
def me(request):
    denied=customer(request)
    if denied: return denied
    return JsonResponse({'email':request.user.email,'role':'customer','account_id':request.account_id,'execution_enabled':False})

@endpoint(['GET'])
def projects(request, project_id=None):
    denied=customer(request)
    if denied: return denied
    with connection.cursor() as c:
        if project_id:
            c.execute('SELECT id,name,created_at FROM projects WHERE account_id=%s AND id=%s',[request.account_id,project_id])
            row=c.fetchone()
            if not row: raise Denied()
            result=dict(zip(['id','name','created_at'],row))
        else:
            c.execute('SELECT id,name,created_at FROM projects WHERE account_id=%s ORDER BY created_at,id LIMIT 100',[request.account_id])
            result=[dict(zip(['id','name','created_at'],r)) for r in c.fetchall()]
    return JsonResponse({'project':result} if project_id else {'projects':result})

@endpoint(['GET','POST'])
def disabled(request, kind, object_id=None, action=None):
    denied=customer(request)
    if denied: return denied
    table={'tasks':'tasks','streams':'tasks','artifacts':'artifacts','conversations':'conversations','operations':'operations'}.get(kind)
    if object_id:
        if not table: raise Denied()
        with connection.cursor() as c:
            c.execute(f'SELECT 1 FROM {table} WHERE account_id=%s AND id=%s',[request.account_id,object_id])
            if not c.fetchone(): raise Denied()
    return JsonResponse({'error':'capability_not_enabled'},status=503)

@endpoint(['POST'], ['email'])
def invite(request,account):
    operator_scope(request,account,'invite')
    email=request.input.get('email','').strip().lower(); validate_email(email)
    user,raw=create_invite(email,account,request.user.pk,request.request_id)
    sent=deliver(user,'onboarding',raw,request.request_id)
    return JsonResponse({'onboarding':'verification_pending','delivery':'sent' if sent else 'uncertain'},status=201)

@endpoint(['POST'], ['actor_id'])
def operator_revoke(request,account):
    operator_scope(request,account,'revoke')
    actor_id=request.input.get('actor_id','')
    if not actor_id.isdecimal(): raise Denied()
    revoke(request.user.pk,account,actor_id,request.request_id)
    return JsonResponse({'revoked':True})

@endpoint(['POST'])
def suspend(request,account):
    operator_scope(request,account,'suspend')
    with transaction.atomic():
        op=uuid.uuid4(); audit(request.user.pk,account,account,'account.suspend','pending',request.request_id,op)
        with connection.cursor() as c:
            c.execute("UPDATE accounts SET status='suspended' WHERE id=%s AND status='active'",[account])
            if c.rowcount!=1: raise Denied()
        Identity.objects.filter(account_id=account).update(epoch=models_f_epoch())
        audit(request.user.pk,account,account,'account.suspend','completed',request.request_id,op)
    return JsonResponse({'suspended':True})

@endpoint(['GET'])
def operator_audit(request,account):
    operator_scope(request,account,'audit')
    with transaction.atomic():
        audit(request.user.pk,account,account,'support.audit_read','completed',request.request_id)
        rows=list(Audit.objects.filter(account_id=account).order_by('-created_at').values('id','operation_id','actor','object_id','action','outcome','request_id','created_at')[:100])
        with connection.cursor() as c:
            c.execute('SELECT id,actor_id,object_id,action,outcome,request_id,created_at FROM audit_events WHERE account_id=%s ORDER BY created_at DESC,id DESC LIMIT 100',[account])
            lifecycle_rows=[dict(zip(['id','actor','object_id','action','outcome','request_id','created_at'],r)) for r in c.fetchall()]
    return JsonResponse({'events':rows,'lifecycle_events':lifecycle_rows})

@endpoint(['GET','POST'])
def forbidden_support(request, **kwargs):
    return JsonResponse({'error':'support_privilege_not_enabled'},status=403)

def missing(request,exception=None): return JsonResponse({'error':'unavailable'},status=404)
def failed(request): return JsonResponse({'error':'temporarily_unavailable'},status=503)
