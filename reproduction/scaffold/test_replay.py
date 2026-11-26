"""Scientific controls for recorded-response replay and the callback transport boundary."""
import json, unittest
from pathlib import Path
from scaffold.experiment import retry_transport
from scaffold.replay_calls import lines, same, text_hash

ROOT=Path(__file__).resolve().parents[1]

class CallControls(unittest.TestCase):
    def test_retry_preserves_request_and_final_response(self):
        cfg=json.loads((ROOT/'scaffold/conditions.json').read_text())['openrouter_gpt55']['transport_retry']
        attempts=iter([{'http_status':503,'body':'','retry_after_seconds':0},
                       {'http_status':200,'body':json.dumps({'choices':[{'message':{'content':'fixture'}}]})}])
        bodies=[]; waits=[]
        def send(q):
            bodies.append(q)
            return next(attempts)
        q={'model':'fixture','messages':[{'role':'user','content':'fixture prompt'}]}
        self.assertEqual(retry_transport(send,waits.append)(q,1,cfg),'fixture')
        self.assertEqual(bodies,[q,q])
        self.assertEqual(len(waits),1)

    def test_terminal_failure_is_not_retried(self):
        cfg=json.loads((ROOT/'scaffold/conditions.json').read_text())['openrouter_gpt55']['transport_retry']
        calls=[]
        def failure(q):
            calls.append(q)
            return {'terminal':True}
        self.assertEqual(retry_transport(failure,lambda _:self.fail())({'model':'test'},'final',cfg),'')
        self.assertEqual(len(calls),1)

    def test_content_commitment_rejects_single_byte_change(self):
        record=next(lines(ROOT/'responses/message_text.jsonl'))
        with self.assertRaises(ValueError):same(text_hash(record['text']+' '),record['sha256'],'text change')

if __name__=='__main__':
    unittest.main()
