import uuid
from django.http import JsonResponse,HttpResponseRedirect
from django.shortcuts import render
from agentai_platform.request_queue import MAX_MESSAGE_CHARS
from agentai_platform.lifecycle.types import Conflict
from . import wiring
from .services import rate
from .views import endpoint,customer

def _live():
    from .chat import execution_on
    return execution_on()
def queue():return wiring.request_queue()
principal=wiring.principal

@endpoint(['GET','POST'],['message','key'],field_limits={'message':MAX_MESSAGE_CHARS}, form='requests')
def requests(request,request_id=None):
    denied=customer(request)
    if denied:return denied
    try:
        if request.method=='POST':
            if request_id:return JsonResponse({'error':'method_not_allowed'},status=405)
            rate('task.create',request.account_id,30,3600)   # per account, on top of the queue and budget caps
            item=queue().submit(principal(request),message=request.input.get('message',''),key=request.input.get('key',''))
            return JsonResponse({'request':item,'execution_enabled':_live()},status=202)
        return JsonResponse({'request':queue().get(principal(request),request_id)} if request_id else {'requests':queue().get(principal(request)),'execution_enabled':_live()})
    except Conflict:return JsonResponse({'error':'request_conflict'},status=409)

@endpoint(['POST'], form='requests')
def cancel(request,request_id):
    denied=customer(request)
    if denied:return denied
    q = queue()
    p = principal(request)
    item = q.get(p, request_id)
    if item['conversation_id']:
        from .chat import service
        result = service().cancel(p, request_id)
    else:
        result = q.cancel(p, request_id)
    return JsonResponse({'request': result}, status=202)

@endpoint(['GET'])
def page(request):
    denied=customer(request)
    if denied:return HttpResponseRedirect('/account/login/')
    return render(request,'accounts/requests.html',{'requests':queue().get(principal(request)),'key':uuid.uuid4().hex,
        'nav':True,'nav_here':'requests','email':request.user.email})
