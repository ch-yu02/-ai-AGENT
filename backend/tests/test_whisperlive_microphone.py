import unittest

from backend.scripts import whisperlive_microphone as mic_module
from backend.scripts.whisperlive_microphone import (
    TranscriptPreviewSyncer,
    choose_audio_device,
    ffmpeg_microphone_command,
    parse_arecord_devices,
)
from backend.scripts.whisperlive_qwen_markdown import WhisperLiveSegment


class WhisperLiveMicrophoneTests(unittest.TestCase):
    def test_parse_arecord_devices(self) -> None:
        output = """
**** List of CAPTURE Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC Analog [ALC Analog]
  Subdevices: 1/1
card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
"""

        devices = parse_arecord_devices(output)

        self.assertEqual(
            devices,
            [
                ("PCH [HDA Intel PCH] ALC Analog", "plughw:0,0"),
                ("Device [USB Audio Device] USB Audio", "plughw:1,0"),
            ],
        )

    def test_choose_audio_device_prefers_usb_or_mic(self) -> None:
        self.assertEqual(
            choose_audio_device(
                [
                    ("PCH ALC Analog", "plughw:0,0"),
                    ("Device USB Audio", "plughw:1,0"),
                ]
            ),
            "plughw:1,0",
        )
        self.assertEqual(
            choose_audio_device([("Internal Capture", "plughw:0,0")]),
            "plughw:0,0",
        )
        self.assertEqual(choose_audio_device([]), "default")

    def test_ffmpeg_microphone_command_outputs_float32_mono(self) -> None:
        command = ffmpeg_microphone_command(
            ffmpeg="/usr/bin/ffmpeg",
            audio_device="plughw:1,0",
            sample_rate=16000,
        )

        self.assertIn("-f", command)
        self.assertIn("alsa", command)
        self.assertIn("plughw:1,0", command)
        self.assertIn("-ac", command)
        self.assertIn("1", command)
        self.assertIn("-ar", command)
        self.assertIn("16000", command)
        self.assertEqual(command[-2:], ["f32le", "pipe:1"])

    def test_transcript_preview_syncer_posts_non_persistent_preview(self) -> None:
        calls: list[tuple[str, str, dict, float]] = []
        original_post_json = mic_module.post_json

        def fake_post_json(base_url, path, body, *, timeout):  # type: ignore[no-untyped-def]
            calls.append((base_url, path, body, timeout))
            return {"status": "accepted"}

        mic_module.post_json = fake_post_json
        try:
            syncer = TranscriptPreviewSyncer(
                base_url="http://backend",
                session_id="lec_test",
                http_timeout=3.0,
                enabled=True,
                min_interval_seconds=0.0,
                min_chars=1,
            )
            syncer._post_preview(
                WhisperLiveSegment(
                    start=1.0,
                    end=2.0,
                    text="临时字幕",
                    completed=False,
                )
            )
        finally:
            mic_module.post_json = original_post_json

        self.assertEqual(len(calls), 1)
        base_url, path, body, timeout = calls[0]
        self.assertEqual(base_url, "http://backend")
        self.assertEqual(path, "/events/transcript-preview")
        self.assertEqual(timeout, 3.0)
        self.assertEqual(body["session_id"], "lec_test")
        self.assertEqual(body["payload"]["text"], "临时字幕")
        self.assertFalse(body["payload"]["is_final"])


if __name__ == "__main__":
    unittest.main()
