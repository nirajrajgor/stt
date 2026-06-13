"""Parakeet transcription pipeline, importable without stt.py's app side
effects (log tee, hotkeys, recorder). Importing this module loads the native
MLX runtime, so tests that use it must carry the e2e marker."""

from pathlib import Path

from huggingface_hub import hf_hub_download
import mlx.core as mx
import noisereduce as nr
import numpy as np
from parakeet_mlx import DecodingConfig, SentenceConfig, from_pretrained
from parakeet_mlx.audio import get_logmel

from text_cleanup import apply_corrections
from voice_commands import apply_voice_commands

PARAKEET_REPO = "mlx-community/parakeet-tdt-0.6b-v2"
SAMPLE_RATE = 16000
# RMS of the quietest 10% of 20 ms frames. Tuned against a MacBook Air built-in
# mic — clean speech sits around 0.003–0.008; music bleed pushes it above ~0.02.
NOISE_FLOOR_THRESHOLD = 0.015


def _load_parakeet(repo):
    # Load from the local cache to avoid a HF Hub revalidation request on every
    # startup; only download if the cache is empty (first run).
    try:
        config_json = hf_hub_download(repo, "config.json", local_files_only=True)
        return from_pretrained(str(Path(config_json).parent))
    except Exception:
        return from_pretrained(repo)


def _noise_floor(audio):
    """10th-percentile RMS across 20 ms frames — a cheap proxy for ambient noise."""
    frame = int(SAMPLE_RATE * 0.02)
    trimmed = audio[: len(audio) // frame * frame]
    if len(trimmed) < frame:
        return 0.0
    frames = trimmed.reshape(-1, frame)
    frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return float(np.percentile(frame_rms, 10))


class Transcriber:
    """Owns the Parakeet model and the settings-derived decoding config."""

    def __init__(self, settings):
        self._denoise_mode = settings.denoise
        self.decoding_config = DecodingConfig(
            sentence=SentenceConfig(silence_gap=settings.utterance_gap)
        )
        self._model = None

    def load_model(self):
        print("Loading Parakeet TDT 0.6B v2 model...")
        self._model = _load_parakeet(PARAKEET_REPO)
        # Cap MLX's buffer cache so it reclaims instead of growing unboundedly
        # with the longest transcription. 512 MB is plenty for intermediates.
        mx.set_cache_limit(512 * 1024 * 1024)
        print("Model loaded.")

    def _should_denoise(self, noise_floor):
        if self._denoise_mode == "off":
            return False
        if self._denoise_mode == "on":
            return True
        return noise_floor > NOISE_FLOOR_THRESHOLD

    def transcribe(self, audio_np):
        """Transcribe a numpy audio array directly, bypassing file I/O + ffmpeg."""
        try:
            audio_flat = audio_np.flatten().astype(np.float32)
            floor = _noise_floor(audio_flat)
            if self._should_denoise(floor):
                # Non-stationary spectral gating so the noise profile tracks
                # music that evolves over time rather than assuming a fixed hum.
                print(f"🔇 Denoising (noise floor {floor:.4f})")
                audio_flat = nr.reduce_noise(
                    y=audio_flat, sr=SAMPLE_RATE, stationary=False
                )
            audio_mx = mx.array(audio_flat)
            mel = get_logmel(audio_mx, self._model.preprocessor_config)
            result = self._model.generate(mel, decoding_config=self.decoding_config)[0]
            raw = result.text.strip()
            edited = apply_voice_commands(result.sentences)
            return raw, apply_corrections(edited)
        finally:
            # parakeet_mlx's non-streaming transcribe() never clears MLX's
            # buffer cache, so cached intermediates from the largest-ever audio
            # clip pin GB of memory until process exit. Drop them between calls.
            mx.clear_cache()
