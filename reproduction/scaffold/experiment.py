"""State-transfer experiment orchestration with a caller-supplied transport.

The transport receives the exact model request body, a stage label, and the
row condition's retry settings. It returns the model's text content, including
the empty string when the observed extraction yielded empty content.
"""
from scoring import protocol
from scaffold import focused, random10, main_matrix, one_shot


def run_episode(task, method, budget, condition, settings, transport, *, pilot_protocol=None):
    """Run one task. Task segments and final instructions are the only task inputs to the model."""
    params=settings[condition]['payload']
    policy=settings[condition].get('transport_retry',{})
    runner=({'focused':focused,'random10':random10}[pilot_protocol] if pilot_protocol else protocol)
    state=''
    visible=''
    stage_records=[]
    for segment in task['segments']:
        visible+='\n'+segment['text']
        prior='' if method=='loop_only' else state
        prompt=runner.build_update_prompt(method,task,segment,prior,budget,visible)
        request=dict(params,messages=[{'role':'user','content':prompt}])
        text=transport(request,segment['segment_id'],policy)
        if not isinstance(text,str):raise TypeError('The transport must return the extracted model text')
        state,audit=runner.compile_state(method,text,visible,budget)
        stage_records.append({'segment':segment['segment_id'],'state':state,'content':text,'compiler':audit})
    prompt=runner.build_final_prompt(method,task,state)
    if method=='mature_ssr_loop':
        compiler=focused if pilot_protocol else main_matrix
        final=compiler.deterministic_mature_final_output(state)
        origin='deterministic'
    else:
        final=transport(dict(params,messages=[{'role':'user','content':prompt}]),'final',policy)
        origin='hosted'
    return {'final_output':final,'final_state':state,'final_origin':origin,'updates':stage_records}


def run_one_shot(task,settings,transport):
    prompt=one_shot.build_prompt(task)
    request=dict(settings['one_shot']['payload'],messages=[{'role':'user','content':prompt}])
    body=transport(request,'one_shot',{})
    # A one-shot transport returns the OpenAI-compatible response body, since the frozen
    # parser extracts both the answer content and the explicit final_state field from it.
    output,state,error=one_shot.parse_response_content(body)
    return {'final_output':output,'final_state':state,'parse_error':error}


def retry_transport(send,sleep):
    """Adapt an individual HTTP attempt to the main-matrix transport interface.

    send returns a dict containing the exact HTTP body and status, or a
    transport failure with a caller-supplied terminal flag. sleep accepts
    a delay in seconds. The adapter performs no network or clock operation
    unless the supplied functions do so.
    """
    def transport(request,stage,retry):
        if not retry:
            raise ValueError('This condition requires its own explicitly configured transport')
        attempts=[]
        limit=retry['max_transport_attempts']
        for i in range(1,limit+1):
            observed=send(request)
            attempts.append(observed)
            code=observed.get('http_status')
            if observed.get('terminal') or (code is not None and code not in retry['retryable_http_statuses']):
                break
            if i<limit:
                sleep(main_matrix.retry_sleep_seconds(retry,i,observed.get('retry_after_seconds')))
        content,*_=main_matrix.extract_response_content({'attempts':attempts},request['model'])
        return content
    return transport
