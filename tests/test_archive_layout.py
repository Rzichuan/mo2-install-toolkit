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


if __name__ == "__main__":
    unittest.main()
