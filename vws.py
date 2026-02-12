import os
import time
import wave
import tempfile
import numpy as np
import random
from PyQt6.QtCore import QUrl, QObject
from PyQt6.QtMultimedia import QSoundEffect

class SoundManager(QObject):
    def __init__(self, volume=1.0, normalize=False, enabled=True):
        super().__init__()
        self.sounds = {}
        self.normalize = normalize
        self.enabled = enabled
        self.sound_files = {
            'SAM': 'vws_sam.wav',
            'AAA': 'vws_aaa.wav',
            'WELCOME': 'welcome' # Directory for random welcome sounds
        }
        self.base_path = os.path.join(os.path.dirname(__file__), 'sounds')
        self.volume = max(0.0, min(1.0, float(volume))) # Clamp 0.0-1.0
        self.interval = 5.0 # Default Interval
        self.last_played = {}
        
        # Initialize players
        self.generate_startup_tone()
        self.generate_synthesized_warnings()
        self._init_sounds()

    def _init_sounds(self):
        """Pre-load sound effects"""
        if not os.path.exists(self.base_path):
            print(f"[VWS] Sounds directory not found: {self.base_path}")
            return

        for name, filename in self.sound_files.items():
            path = os.path.join(self.base_path, filename)

            # Check if directory (Random Selection)
            if os.path.isdir(path):
                files = [f for f in os.listdir(path) if f.lower().endswith('.wav')]
                if files:
                    selected = random.choice(files)
                    path = os.path.join(path, selected)
                    print(f"[VWS] Selected random {name}: {selected}")
                else:
                    print(f"[VWS] No .wav files found in {filename}")
                    continue

            if os.path.exists(path) and os.path.isfile(path):
                # Normalization Logic
                if self.normalize:
                    try:
                        path = self.normalize_audio(path)
                        print(f"[VWS] Normalized {name}")
                    except Exception as e:
                        print(f"[VWS] Normalization failed for {name}: {e}")

                effect = QSoundEffect()
                effect.setSource(QUrl.fromLocalFile(path))
                effect.setVolume(self.volume) 
                self.sounds[name] = effect
                print(f"[VWS] Loaded {name} from {filename}")
            else:
                print(f"[VWS] Warning: File not found {filename}")

    def generate_startup_tone(self):
        """Generate a two-note startup chime (C5, F5)"""
        note_duration = 0.2
        sample_rate = 44100
        
        # Two-note ascending fourth
        frequencies = [523.25, 698.46]
        
        audio_segments = []
        
        for i, freq in enumerate(frequencies):
            # Last note is longer with fade-out
            is_last = (i == len(frequencies) - 1)
            dur = 0.5 if is_last else note_duration
            
            t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
            
            # Sine Wave (Pure Tone)
            wave_data = np.sin(2 * np.pi * freq * t)
            
            # Envelope: Fast Attack (10ms) + Exponential Decay
            attack_len = int(sample_rate * 0.01)
            decay_len = len(t) - attack_len
            
            # Deeper decay on last note for smooth fade-out
            decay_rate = -4.0 if is_last else -2.0
            envelope = np.concatenate([
                np.linspace(0, 1, attack_len),
                np.exp(np.linspace(0, decay_rate, decay_len))
            ])
            
            # Apply envelope and reduce amplitude
            audio_segments.append(wave_data * envelope * 0.8)
            
        # Concatenate notes
        full_audio = np.concatenate(audio_segments)
        
        # Convert to int16
        audio_int16 = (full_audio * 32767).astype(np.int16)
        
        # Save to temp file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.wav')
        with os.fdopen(temp_fd, 'wb') as f:
            with wave.open(f, 'wb') as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(audio_int16.tobytes())
        
        # Normalize if enabled
        if self.normalize:
            try:
                temp_path = self.normalize_audio(temp_path)
                print(f"[VWS] Normalized STARTUP tone")
            except Exception as e:
                print(f"[VWS] Normalization failed for STARTUP: {e}")

        # Load into SoundManager
        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(temp_path))
        effect.setVolume(self.volume)
        self.sounds['STARTUP'] = effect

    def generate_synthesized_warnings(self):
        """Generate specific sine wave warnings for SAM (2-note) and AAA (1-note)"""
        sample_rate = 44100
        
        # --- AAA: Single High Sine Pulse (800Hz) ---
        duration_aaa = 0.15
        t_aaa = np.linspace(0, duration_aaa, int(sample_rate * duration_aaa), endpoint=False)
        wave_aaa = np.sin(2 * np.pi * 1200 * t_aaa) * 0.5
        
        # Apply envelope
        fade_len = int(sample_rate * 0.01)
        env_aaa = np.ones_like(wave_aaa)
        env_aaa[:fade_len] = np.linspace(0, 1, fade_len)
        env_aaa[-fade_len:] = np.linspace(1, 0, fade_len)
        
        self._save_synth_to_effect('AAA_SYNTH', wave_aaa * env_aaa, sample_rate)

        # --- SAM: Single Low Sine Pulse (600Hz) ---
        duration_sam = 0.2
        t_sam = np.linspace(0, duration_sam, int(sample_rate * duration_sam), endpoint=False)
        wave_sam = np.sin(2 * np.pi * 600 * t_sam) * 0.5
        
        # Apply envelope
        fade_len = int(sample_rate * 0.01)
        env_sam = np.ones_like(wave_sam)
        env_sam[:fade_len] = np.linspace(0, 1, fade_len)
        env_sam[-fade_len:] = np.linspace(1, 0, fade_len)
        
        self._save_synth_to_effect('SAM_SYNTH', wave_sam * env_sam, sample_rate)

    def _save_synth_to_effect(self, name, wave_data, sample_rate):
        """Helper to save numpy array to QSoundEffect"""
        audio_int16 = (wave_data * 32767).astype(np.int16)
        temp_fd, temp_path = tempfile.mkstemp(suffix='.wav')
        with os.fdopen(temp_fd, 'wb') as f:
            with wave.open(f, 'wb') as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(audio_int16.tobytes())
        
        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(temp_path))
        effect.setVolume(self.volume)
        self.sounds[name] = effect

    def normalize_audio(self, filepath):
        """Read wav, normalize peak to -0.1dB, write to temp file"""
        with wave.open(filepath, 'rb') as wav_in:
            params = wav_in.getparams()
            
            # Supported formats: 8-bit, 16-bit, 32-bit (int)
            # 24-bit (3 bytes) is tricky with numpy and skipped
            if params.sampwidth not in [1, 2, 4]:
                print(f"[VWS] Skipping normalization for {os.path.basename(filepath)} (Bit depth {params.sampwidth*8} not supported)")
                return filepath

            frames = wav_in.readframes(params.nframes)
            
            # Convert to numpy array based on sample width
            dtype = np.int16
            if params.sampwidth == 1: dtype = np.int8
            elif params.sampwidth == 4: dtype = np.int32
            
            audio_data = np.frombuffer(frames, dtype=dtype)
            
            # Normalize
            max_val = np.max(np.abs(audio_data))
            if max_val > 0:
                target_max = float(np.iinfo(dtype).max) * 0.98 # -0.2dB headroom
                gain = target_max / max_val
                audio_data = (audio_data * gain).astype(dtype)
                
            # Write to temp file
            temp_fd, temp_path = tempfile.mkstemp(suffix='.wav')
            with os.fdopen(temp_fd, 'wb') as f:
                with wave.open(f, 'wb') as wav_out:
                    # Force 16-bit PCM output
                    wav_out.setnchannels(params.nchannels)
                    wav_out.setsampwidth(2) # 16-bit
                    wav_out.setframerate(params.framerate)
                    wav_out.writeframes(audio_data.tobytes())
            
            return temp_path

    def play_warning(self, threat_type):
        """Play sound for threat type if available and not already playing"""
        # Determine sound to play
        sound_key = threat_type
        
        # If VWS disabled, use SYNTH tones
        if not self.enabled:
            if threat_type == 'SAM': sound_key = 'SAM_SYNTH'
            elif threat_type == 'AAA': sound_key = 'AAA_SYNTH'
            
        if sound_key in self.sounds:
            now = time.time()
            if now - self.last_played.get(threat_type, 0) < self.interval:
                return

            effect = self.sounds[sound_key]
            if not effect.isPlaying():
                effect.play()
                self.last_played[threat_type] = now

    def set_interval(self, interval):
        self.interval = float(interval)

    def set_volume(self, volume):
        """Update volume for all sounds (0.0 - 1.0)"""
        self.volume = max(0.0, min(1.0, float(volume)))
        for sound in self.sounds.values():
            sound.setVolume(self.volume)
