"""Check the frozen request IDs, H5 entry and chain digests, and saved pilot outcomes."""
from collections import Counter
import hashlib, json
from pathlib import Path

from scoring import legacy, base
from scoring.freeze import initial_user_prompt_hash, prompt_template_fingerprint


def hash_object(obj, historical=False):
    payload=json.dumps(obj,ensure_ascii=False,separators=(',',':'),sort_keys=True)
    if historical:
        payload+='\n'
    return hashlib.sha256(payload.encode()).hexdigest()


def lines(path):
    with path.open() as handle:
        for text in handle:
            yield json.loads(text)


def check(root):
    tasks={r['task_id']:r for r in lines(root/'inputs/tasks.jsonl')}
    counts={}
    for tier in ('primary','primary_budget300','qwen','qwen_budget300'):
        count=0
        for row,req in zip(lines(root/f'inputs/{tier}.jsonl'),lines(root/f'inputs/{tier}_requests.jsonl'),strict=True):
            if hash_object(req)!=row['logical_request_hash']:
                raise ValueError(f"Request digest mismatch for {row['row_id']}")
            if req['task_id']!=row['task_id'] or req['method']!=row['method'] or req['model_condition_id']!=row['model']:
                raise ValueError('Request/response axes disagree')
            if req['initial_user_prompt_sha256']!=initial_user_prompt_hash(tasks[row['task_id']],row['method'],int(req['budget'])):
                raise ValueError('Initial prompt registration mismatch')
            if req['prompt_template_sha256']!=prompt_template_fingerprint(row['method']):
                raise ValueError('Prompt template registration mismatch')
            choices=row['provider_choices']
            if choices and choices[-1]['content']!=row['final_output']:
                raise ValueError('Retained provider content differs from final answer')
            count+=1
        counts[tier]=count
    tasks={r['task_id']:r for f in ('tasks','historical_tasks') for r in lines(root/f'inputs/{f}.jsonl')}
    layers=Counter()
    seen=set()
    for row in lines(root/'inputs/historical.jsonl'):
        digest=row.pop('distributed_row_sha256')
        if digest!=hash_object(row):
            raise ValueError('Distributed evidence digest mismatch')
        record=row['record']
        key=(row['layer'],record['global_artifact_id'])
        if key in seen:
            raise ValueError('Duplicate historical record')
        seen.add(key)
        entry_hash=hash_object(record,historical=True)
        if entry_hash!=row['historical_manifest_sha256'] or hash_object(dict(record,manifest_entry_hash=entry_hash),historical=True)!=row['historical_chain_sha256']:
            raise ValueError('Historical row digest mismatch')
        score=legacy.score_task if row['scorer']=='main_matrix' else base.score_task
        observed_input=row['observation']
        parsed={k:observed_input[k] for k in ('final_output','final_state')}
        if hash_object(parsed,historical=True)!=record['parsed_output_sha256']:
            raise ValueError('Historical parsed-output digest mismatch')
        observed=score(tasks[record['task_id']],dict(record,**parsed,model=observed_input['returned_model']))
        if hash_object(observed,historical=True)!=record['metric_record_sha256']:
            raise ValueError('Historical metric-record digest mismatch')
        for k,v in row['scores'].items():
            if observed[k]!=v:
                raise ValueError(f'Historical outcome mismatch: {key}, {k}')
        layers[row['layer']]+=1
    if sorted(layers.values())!=[2,4,644]:
        raise ValueError('Unexpected historical row counts')
    return {'logical_requests':counts,'historical_rows':dict(layers)}
