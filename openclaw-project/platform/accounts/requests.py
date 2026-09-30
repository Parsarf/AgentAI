import uuid
from django.db import connection
from django.http import JsonResponse,HttpResponseRedirect
from django.shortcuts import render
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal,NotFound
from agentai_platform.lifecycle.types import Conflict
from .lifecycle import AccountStore
from .services import Denied
from .views import endpoint,customer

def queue():return RequestQueue(AccountStore(connection.settings_dict['NAME']))
def principal(request):return Principal(request.account_id,str(request.user.pk),'customer')

@endpoint(['GET','POST'],['message','key'],field_limits={'message':16000})
def requests(request,request_id=None):
    denied=customer(request)
    if denied:return denied
    try:
        if request.method=='POST':
            if request_id:return JsonResponse({'error':'method_not_allowed'},status=405)
            item=queue().submit(principal(request),message=request.input.get('message',''),key=request.input.get('key',''))
            return JsonResponse({'request':item,'execution_enabled':False},status=202)
        return JsonResponse({'request':queue().get(principal(request),request_id)} if request_id else {'requests':queue().get(principal(request)),'execution_enabled':False})
    except NotFound:raise Denied()
    except Conflict:return JsonResponse({'error':'request_conflict'},status=409)

@endpoint(['POST'])
def cancel(request,request_id):
    denied=customer(request)
    if denied:return denied
    try:return JsonResponse({'request':queue().cancel(principal(request),request_id)},status=202)
    except NotFound:raise Denied()

@endpoint(['GET'])
def page(request):
    denied=customer(request)
    if denied:return HttpResponseRedirect('/account/login/')
    return render(request,'accounts/requests.html',{'requests':queue().get(principal(request)),'key':uuid.uuid4().hex})
