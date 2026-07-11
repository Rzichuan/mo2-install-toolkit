import unittest
from unittest.mock import patch
from mo2_agent_toolkit import nexus

class NexusResolverTests(unittest.TestCase):
    def file(self, mod_id):
        return {'file_id': mod_id * 10, 'file_name': f'mod-{mod_id}.zip', 'category_id': 1, 'uploaded_timestamp': mod_id}

    def candidate(self, mod_id, name='dep'):
        return {'mod': {'game_scoped_id': mod_id, 'name': name}}

    def test_required_dependencies_are_recursive_and_leaf_first(self):
        deps={100:[{'candidate_mod_files':[self.candidate(200)]}],200:[{'candidate_mod_files':[self.candidate(300)]}],300:[]}
        with patch.object(nexus,'materialized_dependencies',side_effect=lambda mid,key:deps[mid]), patch.object(nexus,'preferred_file',side_effect=lambda mid,key:self.file(mid)):
            result=nexus.resolve_batch(100,'secret',set())
        self.assertEqual([x['mod_id'] for x in result['required']],[300,200])
        self.assertEqual(result['target']['file']['file_id'],1000)

    def test_optional_is_not_resolved_or_materialized_until_selected(self):
        deps={100:[{'is_optional':True,'candidate_mod_files':[self.candidate(200)]}]}
        calls=[]
        with patch.object(nexus,'materialized_dependencies',side_effect=lambda mid,key:calls.append(mid) or deps.get(mid,[])), patch.object(nexus,'preferred_file',side_effect=lambda mid,key:self.file(mid)):
            result=nexus.resolve_batch(100,'secret',set())
        self.assertEqual(calls,[100]); self.assertEqual(result['optional'][0]['mod_id'],200)
        self.assertNotIn('file',result['optional'][0])

    def test_selected_optional_is_resolved(self):
        deps={100:[{'is_optional':True,'candidate_mod_files':[self.candidate(200)]}],200:[]}
        with patch.object(nexus,'materialized_dependencies',side_effect=lambda mid,key:deps[mid]), patch.object(nexus,'preferred_file',side_effect=lambda mid,key:self.file(mid)):
            result=nexus.resolve_batch(100,'secret',set(),{'200'})
        self.assertEqual(result['optional'][0]['file']['file_id'],2000)

    def test_or_group_remains_unresolved(self):
        deps={100:[{'candidate_mod_files':[self.candidate(200,'A'),self.candidate(201,'B')]}]}
        with patch.object(nexus,'materialized_dependencies',side_effect=lambda mid,key:deps[mid]): result=nexus.resolve_batch(100,'secret',set())
        self.assertEqual([x['mod_id'] for x in result['unresolved_choices'][0]['candidates']],[200,201])

    def test_installed_candidate_satisfies_or_group(self):
        deps={100:[{'candidate_mod_files':[self.candidate(200),self.candidate(201)]}]}
        with patch.object(nexus,'materialized_dependencies',side_effect=lambda mid,key:deps[mid]), patch.object(nexus,'preferred_file',side_effect=lambda mid,key:self.file(mid)):
            result=nexus.resolve_batch(100,'secret',{'201'})
        self.assertFalse(result['unresolved_choices']); self.assertEqual(result['already_satisfied'][0]['mod_id'],201)

if __name__=='__main__': unittest.main()
