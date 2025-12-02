"""
Voice Command Manager for Video Player
---------------------------------------
Provides voice control for video playback using speech recognition.
Supports common commands like play, pause, next, volume control, etc.
"""

import threading
import queue
import time
from typing import Callable, Optional, Dict, Set
import re

try:
    import speech_recognition as sr

    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    SPEECH_RECOGNITION_AVAILABLE = False
    print("speech_recognition not installed. Install with: pip install SpeechRecognition pyaudio")


class VoiceCommandManager:
    """Manages voice commands for video player control"""

    def __init__(self, controller, logger: Optional[Callable] = None):
        """
        Initialize voice command manager

        Args:
            controller: Video player controller instance
            logger: Optional logging function
        """
        if not SPEECH_RECOGNITION_AVAILABLE:
            raise ImportError("speech_recognition library is required for voice commands")

        self.controller = controller
        self.logger = logger
        self.recognizer = sr.Recognizer()
        self.microphone = None

        # Command listening state
        self.is_listening = False
        self.listen_thread = None
        self.command_queue = queue.Queue()
        self.process_thread = None

        # Wake word detection
        self.use_wake_word = True
        self.wake_words = {'hey player', 'video player', 'player'}
        self.wake_word_detected = False
        self.wake_word_timeout = 5.0  # seconds
        self.last_wake_word_time = 0

        # Command mappings
        self.command_map = self._build_command_map()

        # Recognition settings
        self.recognizer.energy_threshold = 4000
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8

        # Statistics
        self.commands_recognized = 0
        self.commands_executed = 0
        self.recognition_errors = 0

    def _build_command_map(self) -> Dict[str, Callable]:
        """Build mapping of voice commands to controller methods"""
        return {
            # Playback control
            'play': self.controller.toggle_pause,
            'pause': self.controller.toggle_pause,
            'stop': self.controller.stop_video,
            'resume': self.controller.toggle_pause,

            # Navigation
            'next': self.controller.next_video,
            'previous': self.controller.prev_video,
            'skip': self.controller.next_video,
            'back': self.controller.prev_video,
            'next folder': self.controller.next_directory if hasattr(self.controller, 'next_directory') else None,
            'previous folder': self.controller.prev_directory if hasattr(self.controller, 'prev_directory') else None,

            # Seeking
            'forward': self.controller.fast_forward,
            'rewind': self.controller.rewind,
            'fast forward': self.controller.fast_forward,

            # Volume
            'volume up': self.controller.volume_up,
            'volume down': self.controller.volume_down,
            'louder': self.controller.volume_up,
            'quieter': self.controller.volume_down,
            'mute': self.controller.toggle_mute,
            'unmute': self.controller.toggle_mute,

            # Display
            'fullscreen': self.controller.toggle_fullscreen,
            'exit fullscreen': self.controller.toggle_fullscreen,
            'screenshot': self.controller.take_screenshot,
            'overlay': self.controller.toggle_overlay if hasattr(self.controller, 'toggle_overlay') else None,

            # Speed control
            'speed up': self.controller.increase_speed,
            'slow down': self.controller.decrease_speed,
            'normal speed': self.controller.reset_speed_hotkey,
            'faster': self.controller.increase_speed,
            'slower': self.controller.decrease_speed,

            # Monitor switching
            'monitor one': lambda: self.controller.switch_to_monitor(1),
            'monitor two': lambda: self.controller.switch_to_monitor(2),
            'first monitor': lambda: self.controller.switch_to_monitor(1),
            'second monitor': lambda: self.controller.switch_to_monitor(2),
        }

    def _log(self, message: str):
        """Log a message if logger is available"""
        if self.logger:
            self.logger(f"[Voice] {message}")
        else:
            print(f"[Voice] {message}")

    def start_listening(self):
        """Start listening for voice commands"""
        if not SPEECH_RECOGNITION_AVAILABLE:
            self._log("Speech recognition not available")
            return False

        if self.is_listening:
            self._log("Already listening")
            return False

        try:
            # Initialize microphone
            self.microphone = sr.Microphone()

            # Adjust for ambient noise
            self._log("Calibrating microphone for ambient noise...")
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)

            self.is_listening = True

            # Start listening thread
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()

            # Start command processing thread
            self.process_thread = threading.Thread(target=self._process_commands, daemon=True)
            self.process_thread.start()

            mode = "wake word" if self.use_wake_word else "continuous"
            self._log(f"Voice commands active ({mode} mode)")
            if self.use_wake_word:
                self._log(f"Say one of: {', '.join(self.wake_words)}")

            return True

        except Exception as e:
            self._log(f"Failed to start voice recognition: {e}")
            self.is_listening = False
            return False

    def stop_listening(self):
        """Stop listening for voice commands"""
        if not self.is_listening:
            return

        self.is_listening = False
        self.wake_word_detected = False

        # Wait for threads to finish
        if self.listen_thread:
            self.listen_thread.join(timeout=2.0)
        if self.process_thread:
            self.process_thread.join(timeout=2.0)

        self._log("Voice commands stopped")
        self._log(f"Stats - Recognized: {self.commands_recognized}, "
                  f"Executed: {self.commands_executed}, "
                  f"Errors: {self.recognition_errors}")

    def _listen_loop(self):
        """Main listening loop (runs in background thread)"""
        while self.is_listening:
            try:
                with self.microphone as source:
                    # Listen for audio
                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)

                    # Add to queue for processing
                    self.command_queue.put(audio)

            except sr.WaitTimeoutError:
                # Check if wake word has timed out
                if self.wake_word_detected:
                    if time.time() - self.last_wake_word_time > self.wake_word_timeout:
                        self.wake_word_detected = False
                        self._log("Wake word timed out, listening for wake word again")
                continue

            except Exception as e:
                if self.is_listening:  # Only log if we're supposed to be listening
                    self._log(f"Listening error: {e}")
                time.sleep(0.5)

    def _process_commands(self):
        """Process recognized audio (runs in background thread)"""
        while self.is_listening:
            try:
                # Get audio from queue
                audio = self.command_queue.get(timeout=1)

                # Recognize speech
                try:
                    text = self.recognizer.recognize_google(audio).lower()
                    self._log(f"Heard: '{text}'")
                    self.commands_recognized += 1

                    # Check for wake word if enabled
                    if self.use_wake_word and not self.wake_word_detected:
                        if self._check_wake_word(text):
                            self.wake_word_detected = True
                            self.last_wake_word_time = time.time()
                            self._log("Wake word detected! Listening for command...")
                            continue

                    # Process command if wake word is detected or disabled
                    if not self.use_wake_word or self.wake_word_detected:
                        if self._execute_command(text):
                            self.commands_executed += 1
                            # Reset wake word after successful command
                            if self.use_wake_word:
                                self.wake_word_detected = False

                except sr.UnknownValueError:
                    # Speech was unintelligible
                    pass

                except sr.RequestError as e:
                    self._log(f"Recognition service error: {e}")
                    self.recognition_errors += 1
                    time.sleep(1)

            except queue.Empty:
                continue

            except Exception as e:
                self._log(f"Processing error: {e}")
                self.recognition_errors += 1

    def _check_wake_word(self, text: str) -> bool:
        """Check if text contains wake word"""
        text = text.lower().strip()
        for wake_word in self.wake_words:
            if wake_word in text:
                return True
        return False

    def _execute_command(self, text: str) -> bool:
        """
        Execute command based on recognized text

        Returns:
            True if command was recognized and executed
        """
        text = text.lower().strip()

        # Remove wake word if present
        for wake_word in self.wake_words:
            text = text.replace(wake_word, '').strip()

        # Check for direct command matches
        for command, action in self.command_map.items():
            if command in text:
                if action:
                    try:
                        action()
                        self._log(f"Executed: {command}")
                        return True
                    except Exception as e:
                        self._log(f"Error executing '{command}': {e}")
                        return False

        # Check for special commands with parameters
        if self._handle_volume_command(text):
            return True

        if self._handle_speed_command(text):
            return True

        if self._handle_seek_command(text):
            return True

        # Command not recognized
        self._log(f"Command not recognized: '{text}'")
        return False

    def _handle_volume_command(self, text: str) -> bool:
        """Handle volume commands with specific levels"""
        # Pattern: "volume 50", "set volume to 80", etc.
        match = re.search(r'volume\s+(?:to\s+)?(\d+)', text)
        if match:
            try:
                volume = int(match.group(1))
                volume = max(0, min(100, volume))
                self.controller.player.audio_set_volume(volume)
                self.controller.volume = volume
                self._log(f"Set volume to {volume}%")
                return True
            except Exception as e:
                self._log(f"Error setting volume: {e}")
        return False

    def _handle_speed_command(self, text: str) -> bool:
        """Handle speed commands with specific rates"""
        # Pattern: "speed 1.5", "set speed to 2", "play at 0.5 speed", etc.
        match = re.search(r'(?:speed|rate)\s+(?:to\s+)?([0-9.]+)', text)
        if match:
            try:
                speed = float(match.group(1))
                speed = max(0.25, min(2.0, speed))
                self.controller.set_playback_rate(speed)
                self._log(f"Set playback speed to {speed}x")
                return True
            except Exception as e:
                self._log(f"Error setting speed: {e}")
        return False

    def _handle_seek_command(self, text: str) -> bool:
        """Handle seeking commands"""
        # Pattern: "skip 30 seconds", "go back 10 seconds", "jump forward 1 minute"

        # Forward seeking
        match = re.search(r'(?:skip|forward|jump)\s+(\d+)\s+(second|minute)', text)
        if match:
            try:
                amount = int(match.group(1))
                unit = match.group(2)

                seconds = amount if unit == 'second' else amount * 60
                current_time = self.controller.player.get_time()
                new_time = current_time + (seconds * 1000)

                length = self.controller.player.get_length()
                if 0 < length < new_time:
                    new_time = length - 1000

                self.controller.player.set_time(int(new_time))
                self._log(f"Skipped forward {amount} {unit}(s)")
                return True
            except Exception as e:
                self._log(f"Error seeking: {e}")

        # Backward seeking
        match = re.search(r'(?:back|rewind|backwards?)\s+(\d+)\s+(second|minute)', text)
        if match:
            try:
                amount = int(match.group(1))
                unit = match.group(2)

                seconds = amount if unit == 'second' else amount * 60
                current_time = self.controller.player.get_time()
                new_time = max(0, current_time - (seconds * 1000))

                self.controller.player.set_time(int(new_time))
                self._log(f"Went back {amount} {unit}(s)")
                return True
            except Exception as e:
                self._log(f"Error seeking: {e}")

        return False

    def toggle_wake_word(self):
        """Toggle wake word requirement on/off"""
        self.use_wake_word = not self.use_wake_word
        self.wake_word_detected = False

        mode = "enabled" if self.use_wake_word else "disabled"
        self._log(f"Wake word {mode}")

        if self.use_wake_word:
            self._log(f"Say one of: {', '.join(self.wake_words)}")
        else:
            self._log("Listening continuously for commands")

    def add_custom_command(self, command: str, action: Callable):
        """
        Add a custom voice command

        Args:
            command: The voice command text to recognize
            action: Function to call when command is recognized
        """
        self.command_map[command.lower()] = action
        self._log(f"Added custom command: '{command}'")

    def get_available_commands(self) -> list:
        """Get list of all available commands"""
        return sorted([cmd for cmd in self.command_map.keys() if self.command_map[cmd] is not None])

    def cleanup(self):
        """Cleanup resources"""
        self.stop_listening()
        self.microphone = None
        self.recognizer = None