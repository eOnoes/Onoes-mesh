"""Optional private native chat profile. No app endpoint, keys or model call."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
import mesh_launch_candidate as launch

class NativeCodexFrameTests(unittest.TestCase):
    def profile(self):
        return {'codexDesktopOptions':dict(source='native_codex_desktop_messaging',projectDirectory='C:/Owned/Project',transport=dict(
            nodePath=str(Path(sys.executable).resolve()),serverPath=str(Path(__file__).resolve()),nodeSha256='a'*64,serverSha256='b'*64,
            pipePath='\\\\.\\pipe\\codex-app-tools-11111111-1111-4111-8111-111111111111',callerThreadId='11111111-1111-4111-8111-111111111111',discovery='single_local_codex_desktop'))}
    def test_persistent_namespace_needs_no_saved_desktop_instance_id(self):
        profile=self.profile();profile['codexDesktopOptions']['transport']['pipePath']=r'\\.\pipe\codex-app-tools'
        self.assertEqual(launch.codex_frame_fields(profile),profile)

    def test_optional_default_is_unchanged_and_returned_frame_is_a_copy(self):
        self.assertEqual(launch.codex_frame_fields({}),{})
        profile=self.profile();body=launch.codex_frame_fields(profile);self.assertEqual(body,profile)
        body['codexDesktopOptions']['source']='changed';self.assertEqual(profile['codexDesktopOptions']['source'],'native_codex_desktop_messaging')
    def test_unavailable_native_files_do_not_prevent_unrelated_mesh_startup(self):
        profile=self.profile();profile['codexDesktopOptions']['transport']['serverPath']=str(Path(__file__).parent/'not-installed-server.mjs')
        self.assertEqual(launch.codex_frame_fields(profile),profile)
    def test_unknown_or_broadened_native_fields_are_rejected(self):
        cases=[]
        for key,value in [('source','guessed'),('projectDirectory','../other'),('model','unrequested')]:
            p=self.profile();p['codexDesktopOptions'][key]=value;cases.append(p)
        for key,value in [('callerThreadId','echo'),('pipePath','tcp://other'),('nodeSha256','bad'),('discovery','scan-all'),('hostId','other')]:
            p=self.profile();p['codexDesktopOptions']['transport'][key]=value;cases.append(p)
        for p in cases:
            with self.subTest(fields=list(p['codexDesktopOptions'])),self.assertRaises(launch.LaunchError):launch.codex_frame_fields(p)
    def test_native_frame_reuses_the_existing_mind_frame_and_preserves_default(self):
        base={'schema':'existing-frame','mindRecallOptions':{'marker':'synthetic'}}
        profile=self.profile()
        with patch.object(launch,'_mind_frame',return_value=copy.deepcopy(base)):
            actual=launch.native_frame(profile,object(),'unused','unused');self.assertEqual(actual,{**base,**profile})

if __name__=='__main__':unittest.main()
