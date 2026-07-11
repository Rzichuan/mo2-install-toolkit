import json
from pathlib import Path
import tempfile
import unittest

from mo2_agent_toolkit import cli, npc

class NpcWorkflowTests(unittest.TestCase):
    def sample_scan(self, root: Path):
        profile=root/'profiles'/'Default'; profile.mkdir(parents=True)
        for name in npc.PROFILE_FILES: (profile/name).write_text('# header\n',encoding='utf-8-sig')
        mod=root/'mods'/'Kurone'; (mod/'meshes').mkdir(parents=True); (mod/'textures').mkdir(parents=True)
        (mod/'meshes'/'x.nif').write_bytes(b'nif'); (mod/'textures'/'x.dds').write_bytes(b'dds')
        return {'instance':str(root),'profile':'Default','game_data':str(root/'Data'),'sidecar':'patcher.exe',
                'profile_snapshot':npc._snapshot(root,'Default'),'report':{'WinningNpcRecords':[{
                    'BasePlugin':'Skyrim.esm','FaceGenFormId':'000A2C8F','FormKey':'000A2C8F:Skyrim.esm','EditorId':'HousecarlSolitude','Name':'Jordis',
                    'PatchPlan':{'Action':'patch-default-from-winning-face-from-candidate','FaceSourceMod':'Kurone'},
                    'FaceGenCandidates':[{'SourceMod':'Kurone','SourcePlugin':'Kurone.esp','FilePriority':0,'HasMesh':True,'HasTint':True,
                                          'MeshRelativePath':'meshes/x.nif','TintRelativePath':'textures/x.dds'}]}]}}

    def test_unique_complete_candidate_is_auto_planned(self):
        with tempfile.TemporaryDirectory() as td:
            plan=npc.make_plan(self.sample_scan(Path(td)))
            item=plan['items'][0]
            self.assertEqual(item['status'],'ready')
            self.assertTrue(item['appearance_candidate_id'].startswith('npcface:'))
            self.assertEqual(item['npc_key'],'Skyrim.esm:000A2C8F')
            self.assertEqual(len(item['candidates'][0]['mesh_sha256']),64)
            self.assertTrue(item['candidates'][0]['eligible'])
            self.assertEqual(item['candidates'][0]['SourcePlugin'],'Kurone.esp')

    def test_same_mod_multiple_plugins_have_distinct_candidate_ids(self):
        with tempfile.TemporaryDirectory() as td:
            scan=self.sample_scan(Path(td))
            candidates=scan['report']['WinningNpcRecords'][0]['FaceGenCandidates']
            candidates.append({**candidates[0], 'SourcePlugin':'Kurone-B.esp'})
            plan=npc.make_plan(scan)
            item=plan['items'][0]
            self.assertEqual(item['status'],'decision_required')
            self.assertEqual(len({x['candidate_id'] for x in item['candidates']}),2)
            chosen=item['candidates'][1]['candidate_id']
            decided=npc.apply_decisions(plan,{'schema_version':1,'plan_id':plan['plan_id'],'decisions':[{'npc_key':item['npc_key'],'appearance_candidate_id':chosen}]})
            self.assertEqual(decided['items'][0]['appearance_candidate_id'],chosen)

    def test_decision_rejects_unknown_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            plan=npc.make_plan(self.sample_scan(Path(td)))
            with self.assertRaises(npc.NpcError):
                npc.apply_decisions(plan,{'schema_version':1,'plan_id':plan['plan_id'],'decisions':[{'npc_key':'Skyrim.esm:000A2C8F','appearance_candidate_id':'npcface:bad'}]})

    def test_profile_snapshot_invalidates_after_change(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); scan=self.sample_scan(root)
            (root/'profiles'/'Default'/'plugins.txt').write_text('*changed.esp\n',encoding='utf-8-sig')
            self.assertNotEqual(scan['profile_snapshot'],npc._snapshot(root,'Default'))

    def test_apply_rejects_facegen_changed_after_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=npc.make_plan(self.sample_scan(root))
            (root/'mods'/'Kurone'/'meshes'/'x.nif').write_bytes(b'changed')
            with self.assertRaisesRegex(npc.NpcError,'changed after planning'):
                npc.apply_plan(plan,root/'sessions',lambda:[],True)

    def test_cli_exposes_npc_commands(self):
        help_text=cli.parser().format_help()
        self.assertIn('npc',help_text)
        args=cli.parser().parse_args(['npc','verify','plan.json','--json'])
        self.assertEqual(args.npc_command,'verify')

if __name__=='__main__': unittest.main()
