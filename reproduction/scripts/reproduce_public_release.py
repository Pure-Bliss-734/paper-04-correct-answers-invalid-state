"""Replay the paper's saved row populations and tabulate the measured endpoints."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
import subprocess, sys, tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scoring.protocol import json_parse_success
from scripts.lineage import check as check_lineage, hash_object
from metric_v2.reference_scorer.reference_scorer import score as reference_v2
from scripts.independent_executor import run_row as execute_v2
from scaffold.v2_controls import representation_control
from scripts.tables import compare
from scaffold.replay_calls import run as replay_calls
from scoring import controls
from scoring.legacy import score_task
from scoring.task_v2 import derive as derive_v2
from scoring.task_v3 import derive as derive_v3
from scoring.intervals import compute_headline_rows, compute_contrast_rows
from metric_v2.production_scorer import score_row
from metric_v3.evaluator import score_row_v3
from scripts.independent_executor_v3 import run_row
from scripts.analyze_metric_v3_executor import estimate, bootstrap
from scripts.test_metric_v3_invariance import REPS, SIGNATURE, cases, run_case
TIERS={'primary':7200,'qwen':1440,'primary_budget300':800,'qwen_budget300':160,
       'deepseek_sanity':40,'deterministic_validity_suite':36000}
V1=('answer_success','state_governance_success','reliable_composite_success')
V3=('representation_parseable_v3','positive_operational_state_present_v3','exclusion_safety_v3',
    'operational_state_sufficiency_v3','answer_state_consistency_v3','intrinsic_state_validity_v3',
    'carried_state_validity_v3','joint_final_answer_state_success_v3')


def rows(path):
    with path.open() as handle:
        for line in handle:
            yield json.loads(line)


def summarize(records):
    counts=Counter()
    for r in records:
        counts['rows']+=1
        for key in (*V1,'answer_success_v2','carried_state_validity_v2',*V3,'hard_cap','parse_success'):
            counts[key]+=int(r[key])
        counts['legacy_answer_and_invalid']+=int(r[V1[0]] and not r[V1[1]])
        counts['legacy_incorrect_and_valid']+=int(not r[V1[0]] and r[V1[1]])
    if counts['rows']:
        counts['product_of_margins']=counts[V1[0]]*counts[V1[1]]/(counts['rows']**2)
    return dict(counts)


def groups(records, fields):
    subsets=defaultdict(list)
    for r in records:
        subsets[tuple(r[k] for k in fields)].append(r)
    return [dict(zip(fields,k),**summarize(v)) for k,v in sorted(subsets.items())]


def check_cases():
    for case in cases():
        signatures=[]
        for fmt in REPS:
            s,_=run_case(case,fmt)
            signature=tuple(s[k] for k in SIGNATURE)
            if signature[-1]!=case['expected']:
                raise ValueError(f"Invariance control failed: {case['name']} {fmt}")
            signatures.append(signature)
        if len(set(signatures))!=1:
            raise ValueError(f"Representations differ: {case['name']}")
    return {'cases':len(cases()),'renderings':len(cases())*len(REPS)}


def replay(row_output=None):
    task_rows=list(rows(ROOT/'inputs/tasks.jsonl'))
    tasks={r['task_id']:r for r in task_rows}
    if len(tasks)!=40 or len(tasks)!=len(task_rows):
        raise ValueError('Task manifest differs from the forty-task design')
    task_v2={k:derive_v2(v,'') for k,v in tasks.items()}
    task_v3={k:derive_v3(v,'') for k,v in task_v2.items()}
    v2_expected=json.loads((ROOT/'reference/v2_checks.json').read_text())
    rep=representation_control(task_v2)
    if {k:rep[k] for k in ('all_pass','representations')}!=v2_expected['representation']:
        raise ValueError('V2 representation sensitivity differs from the frozen control')
    executor_v2_digest=hashlib.sha256()
    by_tier={}
    bindings={}
    cross_answer=Counter()
    cross_validity=Counter()
    executor=defaultdict(list)
    for tier,n in TIERS.items():
        records=[]
        v2_digests={k:hashlib.sha256() for k in ('production','reference')}
        digest=hashlib.sha256()
        seen=set()
        data=rows(ROOT/'inputs'/f'{tier}.jsonl')
        expected=rows(ROOT/'reference'/f'{tier}.jsonl')
        for row,ref in zip(data,expected,strict=True):
            key=row['row_id']
            task=row['task_id']
            if key in seen or key!=ref['row_id']:
                raise ValueError(f'Invalid row correspondence: {tier}, {key}')
            seen.add(key)
            if tier=='deterministic_validity_suite':
                policy={'random_visible_v1':controls.random_policy,'copy_initial_visible_v1':controls.copy_initial_policy,
                        'carry_all_visible_v1':controls.carry_all_visible_policy,'rule_visible_transition_v1':controls.rule_visible_transition_policy,
                        'oracle_ceiling_control_v1':controls.oracle_ceiling_policy}[row['policy']]
                visible={k:v for k,v in tasks[task].items() if k!='oracle'}
                observation=policy(tasks[task] if policy==controls.oracle_ceiling_policy else visible,{'row_id':key.rsplit('::',1)[0]})
                if hash_object(observation['final_output'])!=row['output_sha256'] or hash_object(observation['final_state'])!=row['state_sha256']:
                    raise ValueError(f'Control state or output differs from the frozen observation: {key}')
                row=dict(row,final_output=observation['final_output'],final_state=observation['final_state'])
            one=score_task(tasks[task],row)
            two=score_row(task_v2[task],row)
            for name,result in [('production',two),('reference',reference_v2(task_v2[task],row))]:
                v2_digests[name].update(bytes.fromhex(hash_object(result)))
            if tier=='primary':
                restricted={k:row[k] for k in ('row_id','task_id','method','model','budget','run_id','final_state')}
                executor_v2_digest.update(bytes.fromhex(hash_object(execute_v2(restricted,task_v2[task]))))
            three=score_row_v3(task_v3[task],dict(row,final_answer_success_v2=two['answer_success_v2']))
            observed={'row_id':key,**{'legacy_v1_'+k:one[k] for k in V1},
                      **{k:two[k] for k in ('answer_success_v2','carried_state_validity_v2')},
                      **{k:three[k] for k in V3}}
            ex=None
            if tier=='primary':
                ex=run_row({'final_state':row['final_state']},task_v3[task])
                observed['executor_action_success_v3']=ex['executor_action_success_v3']
                if two['answer_success_v2']:
                    executor[row['method']].append({'task_id':task,'executor':ex['executor_action_success_v3'],
                                                   'v3':three['carried_state_validity_v3']})
                cross_answer[f"{int(one['answer_success'])}/{int(two['answer_success_v2'])}"]+=1
                cross_validity[f"{int(two['carried_state_validity_v2'])}/{int(three['carried_state_validity_v3'])}"]+=1
            if observed!=ref:
                differing=[k for k,v in ref.items() if observed.get(k)!=v]
                raise ValueError(f'Score disagreement: {tier}, {key}: {differing}')
            evidence=dict(row_id=key,tier=tier,request_sha256=row.get('logical_request_hash'),
                          task_sha256=hash_object(tasks[task]),record_sha256=hash_object(row),
                          parsed_state_sha256=hash_object(three['canonical_state_v3']),
                          scores_sha256=hash_object(observed),executor_sha256=hash_object(ex) if ex else None)
            digest.update(bytes.fromhex(hash_object(evidence)))
            if row_output is not None:
                row_output.write(json.dumps(dict(evidence=evidence,canonical_state=three['canonical_state_v3'],
                                   v2=two,v3=three,executor=ex),sort_keys=True,ensure_ascii=False)+'\n')
            parse_success=json_parse_success(row['final_output'])
            records.append({'task_id':task,'model_condition_id':row['model'],'method':row['method'],
                            'budget':str(row['budget']).removeprefix('budget'),'run_id':str(row['run_id']).removeprefix('run'),
                            'family':tasks[task]['family'],'difficulty':tasks[task]['difficulty'],'policy':row.get('policy',''),
                            'hard_cap':any(row.get('segment_hard_cap',[])),'parse_success':parse_success,
                            **{k:one[k] for k in V1},**{k:observed[k] for k in ('answer_success_v2','carried_state_validity_v2',*V3)}})
        if len(records)!=n:
            raise ValueError(f'{tier} contains {len(records)} rows; expected {n}')
        if {k:v.hexdigest() for k,v in v2_digests.items()}!=v2_expected[tier]:
            raise ValueError(f'Full frozen V2 records differ for {tier}')
        by_tier[tier]=records
        bindings[tier]=digest.hexdigest()
    if executor_v2_digest.hexdigest()!=v2_expected['executor']:
        raise ValueError('V2 independent executor differs from the historical records')
    primary=by_tier['primary']
    totals={tier:summarize(r) for tier,r in by_tier.items()}
    if [totals['primary'][k] for k in ('answer_success_v2','intrinsic_state_validity_v3','carried_state_validity_v3','joint_final_answer_state_success_v3')]!=[696,191,180,173]:
        raise ValueError('Primary totals differ from Table 7')
    interval_rows=[]
    for tier in ('primary','qwen'):
        interval_rows.extend(asdict(r) for r in compute_headline_rows(by_tier[tier],tier,10000,20260704))
    interval_rows.extend(asdict(r) for r in compute_contrast_rows(primary,10000,20260704))
    ex_report={m:{**estimate(r),**{'bootstrap':bootstrap(r,10000,20260813)}} for m,r in executor.items()}
    return {'full_v2_reference_and_production_rows':sum(TIERS.values()),'v2_representation_all_pass':rep['all_pass'],'v2_executor_rows':len(primary),'row_binding_sha256':bindings,'tiers':totals,'task_families':dict(Counter(t['family'] for t in tasks.values())),
            'primary_method':groups(primary,['method']),'primary_model_method':groups(primary,['model_condition_id','method']),
            'primary_model_budget':groups(primary,['model_condition_id','budget']),
            'primary_family':groups(primary,['family']),'primary_difficulty':groups(primary,['difficulty']),
            'primary_run':groups(primary,['run_id']),'primary_parse_success':summarize([r for r in primary if r['parse_success']]),
            'qwen_method':groups(by_tier['qwen'],['method']),'diagnostic_method':groups(by_tier['primary_budget300'],['method']),
            'control_policies':groups(by_tier['deterministic_validity_suite'],['policy']),'intervals':interval_rows,
            'legacy_answer_crosswalk':dict(cross_answer),'v2_v3_crosswalk':dict(cross_validity),
            'executor_by_method':ex_report,'invariance':check_cases(),'provenance':check_lineage(ROOT),'api_calls_performed':0,'passed':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,help='Downloaded ZIP to verify against its manifest')
    parser.add_argument('--output',type=Path,help='Write machine-readable results to this path')
    parser.add_argument('--rows-output',type=Path,help='Write full replayed state, score, executor and digest records in JSON Lines format')
    args=parser.parse_args()
    if args.archive:
        subprocess.run([sys.executable,str(ROOT/'tools/verify_package.py'),'--archive',str(args.archive),'--files-only'],check=True)
    if args.rows_output:
        with args.rows_output.open('x',encoding='utf-8') as handle:
            report=replay(handle)
    else:
        report=replay()
    report['paper_comparison']=compare(report,ROOT/'reference/manuscript_tables.json')
    report['response_replay']=replay_calls(ROOT)
    output=json.dumps(report,sort_keys=True,indent=2)+'\n'
    if args.output:
        args.output.write_text(output)
    else:
        print(output,end='')


if __name__=='__main__':
    main()
