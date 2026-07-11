import unittest
from mo2_agent_toolkit.workflow import WorkflowError, transform_update_profile, transform_profile_apply
from mo2_agent_toolkit.cli import parser

class ProfileStateTests(unittest.TestCase):
 def test_retained_unregistered_is_byte_equivalent(self):
  pl=['# header']; lo=['# header']
  a,b,c,s=transform_update_profile(False,pl,lo,['Keep.esp'],['Keep.esp'])
  self.assertEqual((a,b),(pl,lo)); self.assertEqual(s['keep.esp'],'unregistered')
  self.assertEqual(c['preserved_unregistered_plugins'],['Keep.esp'])
 def test_new_policy(self):
  a,b,c,s=transform_update_profile(True,[],[],['New.esp'],[])
  self.assertEqual((a,b),(['New.esp'],['New.esp'])); self.assertEqual(s['new.esp'],'disabled')
  a,b,c,s=transform_update_profile(False,[],[],['New.esp'],[])
  self.assertEqual((a,b),([],[])); self.assertEqual(s['new.esp'],'unregistered')
 def test_asymmetric_and_duplicate_are_blocked(self):
  for pl,lo in [(['A.esp'],[]),(['A.esp','*A.esp'],['A.esp'])]:
   with self.assertRaises(WorkflowError): transform_update_profile(True,pl,lo,['A.esp'],['A.esp'])
 def test_native_toggle_stays_in_place_and_unregisters(self):
  r=transform_profile_apply(['#','+A','-B'],['*A.esp'],['A.esp'],disable_mod=['A'],unregister_plugin=['A.esp'])
  self.assertEqual(r['modlist_lines'],['#','-A','-B']); self.assertEqual(r['plugins_lines'],[]); self.assertEqual(r['loadorder_lines'],[])
 def test_explicit_nexus_parser(self):
  a=parser().parse_args(['nexus','download','123','456','--json']); self.assertEqual(a.values,['123','456']); self.assertTrue(a.json)
 def test_help_only_parses(self):
  with self.assertRaises(SystemExit) as c: parser().parse_args(['profile','apply','--help'])
  self.assertEqual(c.exception.code,0)
if __name__=='__main__': unittest.main()
