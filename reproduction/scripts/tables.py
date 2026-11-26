"""Compare reaggregated counts, rates and intervals with the displayed paper tables."""
import json
from pathlib import Path

A='answer_success_v2'
V='carried_state_validity_v3'
I='intrinsic_state_validity_v3'
J='joint_final_answer_state_success_v3'
LEGACY=['answer_success','state_governance_success','reliable_composite_success']
METHODS=['loop_only','rolling_summary','rolling_visible_carry_forward','rolling_visible_fields_only','ssr_no_visible_carry','mature_ssr_loop']
CORE=[METHODS[i] for i in (1,2,4,5)]
MODELS=['openrouter_claude48','deepseek_v4pro','openrouter_gpt55','kimi_k26','qwen37max']
POLICIES=['random_visible_v1','copy_initial_visible_v1','carry_all_visible_v1','rule_visible_transition_v1','oracle_ceiling_control_v1']


def ratio(n,d):
    return n/d*100


def pairs(ns,d):
    return [value for n in ns for value in (n,ratio(n,d))]


def indexed(values,key):
    return {r[key]:r for r in values}


def rates(row,fields):
    return [ratio(row[k],row['rows']) for k in fields]


def table_values(report):
    t=report['tiers']
    p=t['primary']
    n=p['rows']
    tab={}
    tab[4]=[[v] for k,v in sorted(report['task_families'].items())]
    tab[6]=[[t[k]['rows']] for k in ('primary','qwen','primary_budget300','qwen_budget300','deterministic_validity_suite','deepseek_sanity')]
    tab[7]=[[x,y,ratio(x,y)] for x,y in [(p[A],n),(p[I],n),(p[V],n),(p[J],n),(p[J],p[A]),(p[A]-p[J],p[A])]]
    tab[8]=[pairs(ns,n) for ns in [[p[J],p[A]-p[J],p[A]],[p[V]-p[J],n-p[A]-p[V]+p[J],n-p[A]],[p[V],n-p[V],n]]]
    tab[9]=[pairs([p[k]],n) for k in ('representation_parseable_v3','positive_operational_state_present_v3','exclusion_safety_v3','operational_state_sufficiency_v3','answer_state_consistency_v3')]
    methods=indexed(report['primary_method'],'method')
    tab[10]=[]
    for m in METHODS:
        r=methods[m]
        row=[r['rows']]+pairs([r[A],r[V],r[J]],r['rows'])
        if r[A]:row.append(ratio(r[J],r[A]))
        tab[10].append(row)
    tab[11]=[]
    for m in CORE:
        r=report['executor_by_method'][m]
        row=[]
        for key in ('v3_yes','v3_no'):
            z=r[key];row.extend([z['executor_success'],z['n']])
            if z['n']:row.append(z['rate']*100)
        if r['risk_difference'] is not None:
            row.extend([r['risk_difference']*100,*[x*100 for x in r['bootstrap']['risk_difference']['ci95']]])
        tab[11].append(row)
    for num,key in ((14,'legacy_answer_crosswalk'),(15,'v2_v3_crosswalk')):
        cross=report[key]; first=[cross['0/0'],cross['0/1']];second=[cross['1/0'],cross['1/1']]
        tab[num]=[first+[sum(first)],second+[sum(second)],[first[0]+second[0],first[1]+second[1],n]]
    by_budget={(r['model_condition_id'],r['budget']):r for r in report['primary_model_budget']}
    tab[16]=[]
    for model in MODELS:
        row=[]
        for budget in ('600','1200'):
            r=by_budget[(model,budget)]
            row.extend(pairs([r['hard_cap'],r[V],r[J]],r['rows']))
        tab[16].append(row)
    tab[17]=[[100*r[k] for k in ('estimate','ci_low','ci_high')] for r in report['intervals']]
    mm={(r['model_condition_id'],r['method']):r for r in report['primary_model_method']}
    tab[18]=[[rates(mm[model,m],LEGACY[-1:])[0] for m in METHODS] for model in MODELS]
    tab[19]=[rates(mm[model,m],LEGACY+['hard_cap']) for model in MODELS for m in CORE]
    tab[20]=[[r['rows']]+rates(r,LEGACY) for r in sorted(report['primary_family'],key=lambda r:r['family'])]
    diff=indexed(report['primary_difficulty'],'difficulty')
    tab[21]=[[diff[k]['rows']]+rates(diff[k],LEGACY) for k in ('easy','medium','hard')]
    tab[22]=[]
    for metric in LEGACY:
        vals=[rates(r,[metric])[0] for r in report['primary_run']]
        tab[22].append(vals+[max(vals)-min(vals)])
    tab[23]=[]
    for metric in LEGACY:
        a=rates(p,[metric])[0];b=rates(report['primary_parse_success'],[metric])[0]
        tab[23].append([a,b,b-a])
    qm=indexed(report['qwen_method'],'method')
    tab[24]=[]
    for key in LEGACY+['legacy_answer_and_invalid','legacy_incorrect_and_valid','conditional']:
        r=[]
        for m in (METHODS[2],METHODS[-1]):
            z=qm[m];num=z[LEGACY[-1]] if key=='conditional' else z[key]
            den=z[LEGACY[0]] if key=='conditional' else z['rows']
            r.extend([num,den,ratio(num,den)])
        tab[24].append(r+[r[5]-r[2]])
    diag=indexed(report['diagnostic_method'],'method')
    tab[25]=[[diag[m]['rows']]+rates(diag[m],LEGACY+['hard_cap']) for m in CORE]
    controls=indexed(report['control_policies'],'policy')
    tab[26]=[[r['rows']]+rates(r,LEGACY) for r in [*[controls[k] for k in POLICIES],t['deepseek_sanity']]]
    grouped=[p]
    for b in ('600','1200'):
        grouped.append({k:sum(r[k] for (m,bb),r in by_budget.items() if bb==b) for k in LEGACY+['rows']})
    grouped.append(t['qwen'])
    tab[27]=[]
    for r in grouped:
        a,v,j=rates(r,LEGACY)
        tab[27].append([a,v,a*v/100,j])
    return tab


def compare(report,reference_path):
    reference=json.loads(reference_path.read_text())
    tab=table_values(report); errors=[];cells=0
    for number,values in tab.items():
        expected=reference[str(number)]
        if len(expected)!=len(values):
            raise ValueError(f'Table {number}: row count differs ({len(expected)}, {len(values)})')
        for i,(r,e) in enumerate(zip(values,expected)):
            if len(r)!=len(e):
                raise ValueError(f'Table {number}, row {i+1}: widths differ ({len(r)}, {len(e)})')
            for idx,(val,target) in enumerate(zip(r,e)):
                decimals=len(target.split('.')[1]) if '.' in target else 0
                allowance=0.5*10**-decimals if decimals else 1e-8
                if abs(val-float(target))>allowance+1e-8:errors.append([number,i+1,idx+1,val,target])
                cells+=1
    if errors:
        raise ValueError(f'Displayed results differ: {errors}')
    return {'data_tables':len(tab),'displayed_values':cells}
