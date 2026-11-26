"""Reconstruct recorded prompts, request bodies, clipped states and final answers from the available messages."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import hashlib, json
from scoring import protocol
from scaffold import focused, random10, one_shot, main_matrix
from scaffold.experiment import run_episode, run_one_shot

TIERS=('primary','primary_budget300','qwen','qwen_budget300','deepseek_sanity','historical')

def lines(path):
    with path.open(encoding='utf-8') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

def text_hash(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def json_hash(obj,pilot=False):
    text=json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return text_hash(text+'\n' if pilot else text)

def same(received,expected,stage):
    if received!=expected:
        raise ValueError(f'{stage}: stored and replayed values differ')

def request_body(parameters,prompt):
    return dict(parameters,messages=[{'role':'user','content':prompt}])

def final_content(final,texts,stats):
    if final['origin']=='deterministic':
        if 'attempts' in final:
            raise ValueError('A deterministic answer has hosted attempts')
        return texts[final['compiled_output_sha256']]
    attempted=final['attempts']
    stats['hosted_final_stages']+=1
    stats['hosted_final_attempts']+=len(attempted)
    for att in attempted:
        for msg in att.get('choices',[]):
            for k,v in msg.items():
                if k.endswith('_sha256'):
                    if v not in texts:raise ValueError('Missing saved choice text')
        stats['final_attempt_'+att['body_status']]+=1
    # The runner consumes the first choice on the last attempt. Failed final requests have no model text.
    choices=attempted[-1].get('choices',[]) if attempted else []
    if not choices or 'content_sha256' not in choices[0]:
        stats['hosted_final_without_nonempty_model_text']+=1
        return ''
    content=texts[choices[0]['content_sha256']]
    stats['hosted_final_with_nonempty_model_text' if content else 'hosted_final_without_nonempty_model_text']+=1
    return content

def walk_episode(task,observation,episode,settings,texts,stats,pilot=False):
    """Replay ordered calls without substituting a newly generated state for a missing observation."""
    method=episode['method'] if pilot else observation['method']
    budget=int(str(episode['budget'] if pilot else observation['budget']).removeprefix('budget'))
    if pilot:
        runner=focused if episode['protocol']=='focused' else random10
        condition='pilot/'+episode['model']
    else:
        runner=protocol
        condition=observation['model']
    params=settings[condition]['payload']
    state='';visible='';journals=episode['updates']
    same(len(journals),len(task['segments']),'task segment count')
    for segment,entry in zip(task['segments'],journals,strict=True):
        stats['update_stages']+=1
        same(segment['segment_id'],entry['segment'],'segment order')
        visible+='\n'+segment['text']
        prior='' if method=='loop_only' else state
        if prior is not None:
            prompt=runner.build_update_prompt(method,task,segment,prior,budget,visible)
            same(text_hash(prompt),entry['prompt_sha256'],'state prompt')
            same(json_hash(request_body(params,prompt),pilot),entry['payload_sha256'],'state request body')
            stats['update_prompt_and_payload_recomputed']+=1
        else:
            stats['update_prompt_requires_missing_prior_state']+=1
        if 'attempt_count' in entry:
            same(entry['attempt_count'],len(entry['attempt_statuses']),'update attempt count')
            stats['known_update_attempts']+=entry['attempt_count']
        else:
            stats['updates_with_unknown_attempt_count']+=1
        status=entry['content_status']
        if status=='exact_content':
            raw=texts[entry['raw_content_sha256']]
            if not raw:raise ValueError('Empty content labelled nonempty')
            stats['update_nonempty_original_content']+=1
        elif status=='empty_extracted_content':
            same(entry['raw_content_sha256'],text_hash(''),'empty state observation')
            raw=''
            stats['update_empty_extracted_content']+=1
        elif status=='digest_only':
            raw=None
            stats['update_digest_only']+=1
        else:raise ValueError('Unknown content status')
        known_out=texts.get(entry['compiled_state_sha256']) if entry.get('compiler_output_retained') else None
        independent=(method=='rolling_visible_fields_only' and runner!=focused)
        if raw is not None or independent:
            state,audit=runner.compile_state(method,raw or '',visible,budget)
            same(text_hash(state),entry['compiled_state_sha256'],'compiled state')
            if known_out is not None:same(known_out,state,'observed and compiled state')
            stats['update_compiler_output_recomputed']+=1
        else:
            state=known_out
            if state is not None:stats['compiled_state_from_exact_saved_text']+=1
    saved_state=observation['final_state']
    if state is not None:same(state,saved_state,'final carried state')
    same(text_hash(saved_state),journals[-1]['compiled_state_sha256'],'saved final state')
    prompt=runner.build_final_prompt(method,task,saved_state)
    payload=request_body(params,prompt)
    stats['final_prompts_materialized']+=1
    if pilot:
        if episode['final']['origin']=='deterministic':
            payload={'construction':'deterministic_mature_ssr_slot_compiler','state_sha256':text_hash(saved_state),
                     'rules':['required_tokens_from_OUT','allowed_paths_from_ALW','NO_B_never_copied']}
        same(json_hash(payload,True),episode['request_series_sha256'],'pilot final request')
        same(json_hash({'final_prompt':prompt,'state_update_prompts':[u['prompt_sha256'] for u in journals]},True),episode['prompt_series_sha256'],'pilot prompt series')
        stats['pilot_final_request_and_prompt_series_recomputed']+=1
    final=episode['final']
    content=final_content(final,texts,stats)
    same(content,observation['final_output'],'recorded final output')
    if final['origin']=='deterministic':
        constructor=focused.deterministic_mature_final_output if pilot else main_matrix.deterministic_mature_final_output
        same(constructor(saved_state),content,'deterministic final answer')
        stats['compiled_final_answers']+=1
    if all(u['content_status']!='digest_only' for u in journals):
        current={u['segment']:u for u in journals}
        def transport(body,stage,policy):
            if stage=='final':
                same(body,payload,'end-to-end final request')
                return content
            entry=current[stage]
            same(json_hash(body,pilot),entry['payload_sha256'],'end-to-end update request')
            return texts[entry['raw_content_sha256']] if entry['content_status']=='exact_content' else ''
        run=run_episode(task,method,budget,condition,settings,transport,pilot_protocol=episode.get('protocol'))
        same(run['final_state'],saved_state,'end-to-end final state')
        same(run['final_output'],content,'end-to-end final answer')
        stats['all_stage_orchestrations_replayed']+=1
    return payload

def run(root):
    settings=json.loads((root/'scaffold/conditions.json').read_text())
    tasks={r['task_id']:r for r in lines(root/'inputs/tasks.jsonl')}
    tasks.update({r['task_id']:r for r in json.loads((root/'scaffold/pilot_additional_tasks.json').read_text())})
    texts={}
    for row in lines(root/'responses/message_text.jsonl'):
        h=row['sha256']
        if h in texts or text_hash(row['text'])!=h:raise ValueError('Invalid message dictionary')
        texts[h]=row['text']
    report={}
    for tier in TIERS:
        stats=Counter()
        for o,ep in zip(lines(root/f'inputs/{tier}.jsonl'),lines(root/f'responses/{tier}.jsonl'),strict=True):
            stats['episodes']+=1
            k=o['layer']+'::'+o['record']['global_artifact_id'] if tier=='historical' else o['row_id']
            same(k,ep['row_id'],'episode join')
            task=tasks[ep['task_id'] if tier=='historical' else o['task_id']]
            if tier=='deepseek_sanity':
                final=ep['final']
                content=final_content(final,texts,stats)
                prompt=one_shot.build_prompt(task)
                same(text_hash(prompt),final['prompt_sha256'],'one-shot prompt')
                same(json_hash(request_body(settings['one_shot']['payload'],prompt)),final['payload_sha256'],'one-shot request')
                # Recreate only the OpenAI-compatible choice surface read by the frozen parser.
                body=json.dumps({'choices':[{'message':{'content':content}}]},ensure_ascii=False)
                out,state,err=one_shot.parse_response_content(body)
                same(out,o['final_output'],'one-shot answer')
                same(state,o['final_state'],'one-shot state')
                def transport(request,stage,policy):
                    same(json_hash(request),final['payload_sha256'],'one-shot orchestrator request')
                    return body
                result=run_one_shot(task,settings,transport)
                same(result['final_output'],o['final_output'],'one-shot orchestrator answer')
                same(result['final_state'],o['final_state'],'one-shot orchestrator state')
                stats['all_stage_orchestrations_replayed']+=1
                stats['one_shot_parse_and_request_recomputed']+=1
            elif tier=='historical':
                walk_episode(task,o['observation'],ep,settings,texts,stats,pilot=True)
            else:
                walk_episode(task,o,ep,settings,texts,stats)
        report[tier]=dict(stats)
    return {'populations':report,'distinct_texts':len(texts),'api_calls_performed':0}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tier',choices=TIERS)
    parser.add_argument('--row-id',help='Show attempt evidence and available exact text for this episode')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if bool(args.tier)!=bool(args.row_id):parser.error('--tier and --row-id must be used together')
    if not args.tier:
        print(json.dumps(run(root),indent=2,sort_keys=True))
        return
    texts={r['sha256']:r['text'] for r in lines(root/'responses/message_text.jsonl')}
    for row in lines(root/f'responses/{args.tier}.jsonl'):
        if row['row_id']!=args.row_id:continue
        for update in row['updates']:
            if update['content_status']=='exact_content':update['text']=texts[update['raw_content_sha256']]
            if update['content_status']=='empty_extracted_content':update['text']=''
        for attempt in row['final'].get('attempts',[]):
            for choice in attempt.get('choices',[]):
                for k in ('content','refusal','reasoning_content','reasoning'):
                    if k+'_sha256' in choice:choice[k]=texts[choice[k+'_sha256']]
        if row['final']['origin']=='deterministic':row['final']['compiled_output']=texts[row['final']['compiled_output_sha256']]
        print(json.dumps(row,ensure_ascii=False,indent=2))
        return
    parser.error('Unknown row identifier in this tier')


if __name__=='__main__':
    main()
