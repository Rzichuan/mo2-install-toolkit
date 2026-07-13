import unittest

from mo2_agent_toolkit.workflow import detect_layout


def file(path: str, size: int = 1) -> dict:
    return {"path": path, "directory": False, "size": size}


def directory(path: str) -> dict:
    return {"path": path, "directory": True, "size": 0}


class ArchiveLayoutTests(unittest.TestCase):
    def test_elegant_merchant_single_wrapper_is_flattened(self):
        layout = detect_layout([
            directory("Elegant Merchant Clothes 3BA-SMP"),
            file("Elegant Merchant Clothes 3BA-SMP/ElegantMerchantClothes.esp"),
            file("Elegant Merchant Clothes 3BA-SMP/meshes/armor/example.nif"),
            file("Elegant Merchant Clothes 3BA-SMP/CalienteTools/BodySlide/SliderSets/example.xml"),
        ])
        self.assertTrue(layout["flatten"])
        self.assertEqual(layout["nesting_root"], "Elegant Merchant Clothes 3BA-SMP")
        self.assertEqual(layout["effective_root_entries"], ["CalienteTools", "ElegantMerchantClothes.esp", "meshes"])

    def test_wrapper_with_esp_and_skse_is_flattened(self):
        layout = detect_layout([
            file("Wrapper/RaySense.esp"),
            file("Wrapper/SKSE/Plugins/RaySense.dll"),
        ])
        self.assertTrue(layout["flatten"])
        self.assertEqual(layout["plugin_count"], 1)

    def test_wrapper_with_sound_only_is_flattened(self):
        layout = detect_layout([file("Voice Pack/Sound/Voice/example.fuz")])
        self.assertTrue(layout["flatten"])
        self.assertEqual(layout["effective_root_entries"], ["Sound"])

    def test_wrapper_with_animation_and_nemesis_is_flattened(self):
        layout = detect_layout([
            file("Animations/meshes/actors/character/animations/a.hkx"),
            file("Animations/Nemesis_Engine/mod/example/info.ini"),
        ])
        self.assertTrue(layout["flatten"])
        self.assertTrue(layout["has_nemesis_patch"])

    def test_metadata_at_root_does_not_block_wrapper(self):
        layout = detect_layout([
            file("readme.txt", 0), file("preview.png"), file("Wrapper/Test.esp")
        ])
        self.assertTrue(layout["flatten"])
        self.assertEqual(layout["nesting_root"], "Wrapper")

    def test_root_plugin_prevents_flattening_other_directory(self):
        layout = detect_layout([
            file("RootPlugin.esp"), file("Optional/meshes/example.nif")
        ])
        self.assertFalse(layout["flatten"])
        self.assertIsNone(layout["nesting_root"])

    def test_standard_data_directory_is_not_a_wrapper(self):
        layout = detect_layout([file("textures/example.dds")])
        self.assertFalse(layout["flatten"])
        self.assertEqual(layout["type"], "mo2")

    def test_real_root_data_directory_blocks_flattening_other_child(self):
        layout = detect_layout([
            file("meshes/root.nif"), file("Optional/textures/optional.dds")
        ])
        self.assertFalse(layout["flatten"])
        self.assertIsNone(layout["nesting_root"])

    def test_bodyslide_preset_is_informational(self):
        layout = detect_layout([file("CalienteTools/BodySlide/SliderPresets/Preset.xml")])
        self.assertTrue(layout["has_bodyslide_preset"])
        self.assertEqual(layout["manual_post_install_steps"][0]["level"], "informational")

    def test_prebuilt_behavior_only_requests_review(self):
        layout = detect_layout([file("meshes/actors/character/behaviors/example.hkx")])
        self.assertEqual(layout["manual_post_install_steps"][0]["tool"], "Behavior generator")


    def test_top_level_data_folder_is_a_supported_handler(self):
        layout = detect_layout([
            file("Data/meshes/example.nif"),
            file("Data/Example.esp"),
            file("README.txt"),
        ], "Example.zip")
        self.assertEqual(layout["handler"], "data-folder")
        self.assertEqual(layout["support_status"], "supported")
        self.assertEqual(layout["nesting_root"], "Data")
        self.assertEqual(layout["effective_root_entries"], ["Example.esp", "meshes", "README.txt"])

    def test_xml_fomod_with_top_level_data_remains_supported(self):
        layout = detect_layout([
            file("fomod/ModuleConfig.xml"),
            file("Data/Example.esp"),
        ], "Example.zip")
        self.assertEqual(layout["handler"], "fomod")
        self.assertEqual(layout["support_status"], "supported")
        self.assertFalse(layout["flatten"])

    def test_data_folder_with_unknown_sibling_is_not_guessed(self):
        layout = detect_layout([
            file("Data/Example.esp"),
            file("Extras/Optional.txt"),
        ], "Example.zip")
        self.assertEqual(layout["handler"], "unsupported")
        self.assertEqual(layout["support_status"], "unsupported")
        self.assertEqual(layout["support_reason"], "ambiguous_data_folder")

    def test_wrapper_around_data_folder_is_not_installed_with_nested_data(self):
        layout = detect_layout([file("Wrapper/Data/Example.esp")], "Example.zip")
        self.assertEqual(layout["handler"], "unsupported")
        self.assertEqual(layout["support_reason"], "nested_data_folder")

    def test_scripted_fomod_is_classified_as_risky(self):
        layout = detect_layout([
            file("fomod/ModuleConfig.xml"),
            file("fomod/Script.cs"),
            file("Example.esp"),
        ], "Example.zip")
        self.assertEqual(layout["handler"], "unsupported")
        self.assertEqual(layout["support_status"], "risky")
        self.assertEqual(layout["installer_risk"]["type"], "fomod_csharp")

    def test_explicit_installer_is_blocked_but_mod_tool_executable_is_allowed(self):
        risky = detect_layout([file("Setup.exe"), file("Data/Example.esp")], "Example.zip")
        self.assertEqual(risky["support_status"], "risky")
        tool = detect_layout([file("tools/ExampleTool.exe"), file("Example.esp")], "Example.zip")
        self.assertEqual(tool["handler"], "simple")
        self.assertEqual(tool["support_status"], "supported")

    def test_omod_extension_is_classified_as_risky(self):
        layout = detect_layout([file("textures/example.dds")], "Example.omod")
        self.assertEqual(layout["support_status"], "risky")
        self.assertEqual(layout["installer_risk"]["type"], "omod")


if __name__ == "__main__":
    unittest.main()
