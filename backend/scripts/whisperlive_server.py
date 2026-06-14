"""Run a local WhisperLive OpenVINO server for EDU-Mate smoke tests.

This wrapper keeps WhisperLive setup behind the repo's ``scripts/dev.sh`` entry
point and avoids depending on the upstream ``run_server.py`` file being present
on disk. The actual WhisperLive package is installed into the OpenVINO Python
environment by ``scripts/dev.sh install-whisperlive``.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import types


def install_optional_dependency_stubs() -> None:
    """Stub WhisperLive imports that are not used by the OpenVINO smoke path."""
    if importlib.util.find_spec("faster_whisper") is None:
        faster_whisper = types.ModuleType("faster_whisper")

        class UnavailableWhisperModel:
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError(
                    "faster-whisper is not installed in this lightweight "
                    "WhisperLive OpenVINO setup."
                )

        faster_whisper.WhisperModel = UnavailableWhisperModel
        sys.modules["faster_whisper"] = faster_whisper

    if importlib.util.find_spec("librosa") is None:
        sys.modules["librosa"] = types.ModuleType("librosa")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Start WhisperLive with the OpenVINO backend."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", "-p", type=int, default=9090)
    parser.add_argument("--backend", "-b", default="openvino", choices=["openvino"])
    parser.add_argument("--max-clients", type=int, default=1)
    parser.add_argument("--max-connection-time", type=int, default=600)
    parser.add_argument("--cache-path", default="~/.cache/whisper-live/")
    parser.add_argument("--omp-num-threads", type=int, default=1)
    parser.add_argument(
        "--allow-cpu-fallback",
        action="store_true",
        help="Start even if OpenVINO does not report a GPU device.",
    )
    parser.add_argument(
        "--raw-pcm-input",
        action="store_true",
        help="Accept int16 PCM frames instead of float32 frames.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Start the WhisperLive server."""
    args = parse_args(argv or sys.argv[1:])
    os.environ.setdefault("OMP_NUM_THREADS", str(args.omp_num_threads))
    install_optional_dependency_stubs()
    try:
        import openvino as ov  # noqa: PLC0415
        from whisper_live.server import TranscriptionServer  # noqa: PLC0415
    except ImportError as exc:
        print(
            "WhisperLive dependencies are missing. Run: "
            "scripts/dev.sh install-whisperlive",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    devices = ov.Core().available_devices
    print(f"OpenVINO devices: {devices}", flush=True)
    if not args.allow_cpu_fallback and not any(device.startswith("GPU") for device in devices):
        print(
            "OpenVINO GPU/iGPU device is not visible. Re-run with "
            "--allow-cpu-fallback to test on CPU.",
            file=sys.stderr,
        )
        return 2
    print(
        "Starting WhisperLive OpenVINO server. "
        "The upstream OpenVINO backend selects GPU when available.",
        flush=True,
    )
    server = TranscriptionServer()
    try:
        server.run(
            args.host,
            port=args.port,
            backend=args.backend,
            max_clients=args.max_clients,
            max_connection_time=args.max_connection_time,
            cache_path=args.cache_path,
            raw_pcm_input=args.raw_pcm_input,
        )
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
